# crawler.py
import asyncio
import random
import re
import json
from pathlib import Path
from playwright.async_api import async_playwright, BrowserContext, Page
from config import (
    BASE_URL,
    NEXT_PAGE_SELECTORS,
    PAGE_JUMP_INPUT,
    PAGE_JUMP_BTN,
    USER_DATA_DIR,
    VIEWPORT,
    USER_AGENT,
    BROWSER_ARGS,
    BLACKLIST_FILE,
)
from utils import extract_item_id, normalize_link
from filter import filter_professional_sellers
from logger import logger

# 卖家昵称映射文件
SELLER_NAME_MAP_FILE = Path(BLACKLIST_FILE).parent / "seller_name_map.json"


class GoofishCrawler:
    def __init__(self):
        self.playwright = None
        self.context: BrowserContext = None
        self.page: Page = None
        self.blacklist = set()          # 卖家ID黑名单
        self.seller_name_map = {}       # seller_id -> seller_name 昵称缓存
        self.seller_cache = {}          # seller_id -> is_professional (bool)
        self.item_seller_cache = {}     # link -> seller_id
        self.seller_name_cache = {}     # seller_id -> seller_name (运行时)

    async def start(self, headless=False):
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=headless,
            viewport=VIEWPORT,
            user_agent=USER_AGENT,
            args=BROWSER_ARGS
        )
        self.page = await self.context.new_page()
        logger.info("浏览器上下文已启动")
        self.load_blacklist()
        self.load_seller_name_map()

    async def close(self):
        if self.page:
            try: await self.page.close()
            except: pass
            finally: self.page = None
        if self.context:
            try: await self.context.close()
            except: pass
            finally: self.context = None
        if self.playwright:
            try: await self.playwright.stop()
            except: pass
            finally: self.playwright = None
        logger.info("浏览器已关闭")

    def load_blacklist(self):
        """从文件加载卖家ID黑名单"""
        self.blacklist = set()
        if BLACKLIST_FILE.exists():
            try:
                with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
                    self.blacklist = set(line.strip() for line in f if line.strip())
                logger.info(f"已加载黑名单，共 {len(self.blacklist)} 个卖家ID")
            except Exception as e:
                logger.error(f"读取黑名单失败: {e}，使用空黑名单")

    def save_blacklist(self):
        """保存卖家ID黑名单到文件"""
        try:
            with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
                for sid in self.blacklist:
                    f.write(sid + "\n")
            logger.info(f"黑名单已保存，共 {len(self.blacklist)} 个卖家ID")
        except Exception as e:
            logger.error(f"保存黑名单失败: {e}")

    def load_seller_name_map(self):
        """加载卖家ID到昵称的映射"""
        if SELLER_NAME_MAP_FILE.exists():
            try:
                with open(SELLER_NAME_MAP_FILE, "r", encoding="utf-8") as f:
                    self.seller_name_map = json.load(f)
                logger.info(f"已加载卖家昵称映射，共 {len(self.seller_name_map)} 条")
            except Exception as e:
                logger.error(f"读取卖家昵称映射失败: {e}，使用空映射")
                self.seller_name_map = {}
        else:
            self.seller_name_map = {}

    def save_seller_name_map(self):
        """保存卖家ID到昵称的映射"""
        try:
            with open(SELLER_NAME_MAP_FILE, "w", encoding="utf-8") as f:
                json.dump(self.seller_name_map, f, ensure_ascii=False, indent=2)
            logger.info(f"卖家昵称映射已保存，共 {len(self.seller_name_map)} 条")
        except Exception as e:
            logger.error(f"保存卖家昵称映射失败: {e}")

    def update_seller_name(self, seller_id, seller_name):
        """更新卖家ID对应的昵称（覆盖旧昵称）"""
        if seller_id and seller_name:
            self.seller_name_map[str(seller_id)] = seller_name
            self.seller_name_cache[str(seller_id)] = seller_name

    async def search(self, keyword: str, start_page: int, max_pages: int,
                     check_professional: bool = True):
        results = []
        logger.info(f"开始搜索关键词: {keyword}, 起始页: {start_page}, 计划页数: {max_pages}")

        # 存储从搜索接口提取的完整商品信息：itemId -> {title, price, seller_name}
        item_map = {}

        async def handle_search_response(response):
            nonlocal item_map
            try:
                if response.request.resource_type not in ("xhr", "fetch"):
                    return
                if "idlemtopsearch.pc.search" not in response.url:
                    return
                body = await response.text()
                data = json.loads(body)

                def extract_fields(obj):
                    """递归查找包含 itemId 的对象，返回 {itemId, title, price, seller_name}"""
                    if isinstance(obj, dict):
                        if "itemId" in obj and "title" in obj:
                            detail = obj.get("detailParams", {})
                            price_val = detail.get("soldPrice", "")
                            if not price_val:
                                price_list = obj.get("price", [])
                                if isinstance(price_list, list):
                                    price_text = ""
                                    for p in price_list:
                                        if isinstance(p, dict) and p.get("text"):
                                            price_text += p["text"]
                                    m = re.search(r'\d+(?:\.\d+)?', price_text)
                                    if m:
                                        price_val = m.group(0)
                            seller_name = detail.get("userNick", "")
                            return {
                                "itemId": str(obj["itemId"]),
                                "title": obj.get("title", ""),
                                "price": price_val,
                                "seller_name": seller_name
                            }
                        for v in obj.values():
                            res = extract_fields(v)
                            if res:
                                return res
                    elif isinstance(obj, list):
                        for item in obj:
                            res = extract_fields(item)
                            if res:
                                return res
                    return None

                result_list = data.get("data", {}).get("resultList", [])
                for item_data in result_list:
                    info = extract_fields(item_data)
                    if info:
                        item_map[info["itemId"]] = info

                if item_map:
                    logger.info(f"从搜索接口提取到 {len(item_map)} 个商品完整信息")
            except Exception as e:
                logger.debug(f"解析搜索接口失败: {e}")

        self.page.on("response", handle_search_response)

        base_url = BASE_URL.format(keyword=keyword)
        await self.page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
        await self.page.wait_for_selector("a[href*='/item']", timeout=20000)
        await asyncio.sleep(1.5)

        if start_page > 1:
            if await self._jump_to_page(start_page):
                logger.info(f"成功跳转到第 {start_page} 页")
                await asyncio.sleep(1.2)
            else:
                logger.warning("跳转失败，从第一页开始")
                start_page = 1

        current_items = []
        for _ in range(3):
            current_items = await self._extract_items_from_page()
            if current_items:
                break
            await asyncio.sleep(0.5)

        self._enrich_items(current_items, item_map)

        existing_ids = {extract_item_id(item['link']) for item in current_items}
        logger.info(f"第 {start_page} 页提取 {len(current_items)} 个商品")

        if check_professional:
            current_items = await self._filter_page(current_items, check_professional)
        results.extend(current_items)

        for page_num in range(start_page + 1, start_page + max_pages):
            logger.info(f"准备采集第 {page_num} 页...")
            page_items = []

            if await self._jump_to_page(page_num):
                await asyncio.sleep(1.5)
                page_items = await self._extract_items_from_page()
            else:
                logger.warning("页码跳转失败，尝试点击“下一页”按钮...")
                page_items = await self._click_next_page(existing_ids)

            if not page_items:
                logger.warning("翻页失败，停止采集")
                break

            self._enrich_items(page_items, item_map)

            new_unique = [it for it in page_items if extract_item_id(it['link']) not in existing_ids]
            if not new_unique:
                logger.warning(f"第 {page_num} 页无新增商品，可能已到末页，停止采集")
                break

            existing_ids.update(extract_item_id(item['link']) for item in new_unique)
            logger.info(f"第 {page_num} 页新增 {len(new_unique)} 个商品")

            if check_professional:
                new_unique = await self._filter_page(new_unique, check_professional)
            results.extend(new_unique)

        self.page.remove_listener("response", handle_search_response)

        unique_results = self._deduplicate(results)
        logger.info(f"采集完成，去重后共 {len(unique_results)} 个商品")
        self.save_blacklist()
        self.save_seller_name_map()
        return unique_results

    def _enrich_items(self, items, item_map):
        """根据 itemId 从 item_map 补全商品信息"""
        for item in items:
            item_id = extract_item_id(item['link'])
            if item_id in item_map:
                info = item_map[item_id]
                if not item.get('title') and info.get('title'):
                    item['title'] = info['title']
                if not item.get('price') and info.get('price'):
                    price_str = str(info['price'])
                    if not price_str.startswith('¥'):
                        price_str = '¥' + price_str
                    item['price'] = price_str
                if not item.get('seller_name') and info.get('seller_name'):
                    item['seller_name'] = info['seller_name']
        return items

    async def _extract_items_from_page(self) -> list:
        """从 DOM 提取商品链接，后续由接口数据补全"""
        js_code = r"""
            () => {
                const links = document.querySelectorAll("a[href*='/item']");
                const seen = new Set();
                const result = [];
                for (const link of links) {
                    const href = link.href;
                    if (!href || href.includes('/item') === false) continue;
                    const idMatch = href.match(/[?&]id=(\d+)/);
                    const itemId = idMatch ? idMatch[1] : href;
                    if (seen.has(itemId)) continue;
                    seen.add(itemId);
                    result.push({
                        title: '',
                        price: '',
                        link: href,
                        seller_id: null,
                        seller_name: null
                    });
                }
                return result;
            }
        """
        for attempt in range(3):
            try:
                return await self.page.evaluate(js_code)
            except Exception as e:
                if "Execution context was destroyed" in str(e) or "navigation" in str(e).lower():
                    logger.warning(f"页面导航中，重试提取 ({attempt+1}/3)")
                    await asyncio.sleep(1)
                else:
                    logger.error(f"提取商品失败: {e}")
                    break
        return []

    async def _jump_to_page(self, target_page: int) -> bool:
        try:
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.3)

            success = await self.page.evaluate("""
                (target_page) => {
                    const iframes = document.querySelectorAll('iframe');
                    iframes.forEach(f => f.style.display = 'none');
                    const modals = document.querySelectorAll('.ant-modal-wrap, [class*="login-modal"], [class*="modal"]');
                    modals.forEach(m => m.style.display = 'none');

                    const input = document.querySelector('[class*="search-pagination-to-page-container"] input');
                    if (!input) return false;

                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    nativeInputValueSetter.call(input, String(target_page));
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));

                    const btn = document.querySelector('[class*="search-pagination-to-page-container"] button');
                    if (!btn) return false;
                    btn.click();
                    return true;
                }
            """, target_page)

            if success:
                logger.info(f"JS 方式跳转到第 {target_page} 页成功")
                return True
            else:
                logger.warning("JS 方式跳转失败，未找到输入框或按钮")
                return False
        except Exception as e:
            logger.warning(f"跳转操作异常: {e}")
            return False

    async def _click_next_page(self, existing_ids: set) -> list:
        old_link_count = await self.page.evaluate(
            "() => document.querySelectorAll(\"a[href*='/item']\").length"
        )
        clicked = False
        for selector in NEXT_PAGE_SELECTORS:
            try:
                btn = await self.page.wait_for_selector(selector, timeout=2000)
                if btn and await btn.is_enabled():
                    await btn.scroll_into_view_if_needed()
                    await btn.click()
                    clicked = True
                    break
            except:
                continue

        if not clicked:
            js_click = r"""
                () => {
                    const all = document.querySelectorAll('*');
                    for (const el of all) {
                        if (el.offsetParent === null && el.tagName.toLowerCase() !== 'body') continue;
                        const text = (el.innerText || '').trim();
                        if (text === '>' || text === '下一页' || text === '下一頁') {
                            let clickable = el;
                            while (clickable && clickable.tagName.toLowerCase() !== 'body') {
                                if (['button', 'a', 'li'].includes(clickable.tagName.toLowerCase())) break;
                                clickable = clickable.parentElement;
                            }
                            if (clickable && clickable.tagName.toLowerCase() !== 'body') {
                                clickable.click();
                                return true;
                            }
                        }
                    }
                    return false;
                }
            """
            try:
                clicked = await self.page.evaluate(js_click)
                if clicked:
                    logger.info("通过 JS 点击翻页按钮")
            except:
                clicked = False

        if not clicked:
            logger.warning("未找到可用的翻页按钮")
            return []

        try:
            await self.page.wait_for_function(
                """(oldCount) => {
                    const links = document.querySelectorAll("a[href*='/item']");
                    return links.length > oldCount;
                }""",
                arg=old_link_count,
                timeout=10000
            )
        except Exception:
            pass

        await asyncio.sleep(0.5)
        new_items = await self._extract_items_from_page()
        new_unique = [it for it in new_items if extract_item_id(it['link']) not in existing_ids]
        return new_unique

    def _deduplicate(self, items: list) -> list:
        seen = set()
        unique = []
        for item in items:
            item_id = extract_item_id(item['link'])
            if item_id not in seen:
                seen.add(item_id)
                unique.append(item)
        return unique

    async def _filter_page(self, items: list, check_enabled: bool) -> list:
        return await filter_professional_sellers(
            items,
            self.blacklist,
            self.seller_cache,
            self.item_seller_cache,
            self.seller_name_cache,
            self.context,
            check_enabled
        )