# filter.py
import asyncio
import json
import random
import re
from playwright.async_api import BrowserContext
from config import (
    DETAIL_API_PATTERN,
    LOGIN_USER_API_PATTERN,
    SELLER_ITEM_COUNT_THRESHOLD,
    CHECK_SELLER_TIMEOUT,
    MAX_CONCURRENCY,
)
from utils import extract_number
from logger import logger

# 卖出数量阈值，用于在无法提取“在售”时辅助判断专业商家
SELL_COUNT_THRESHOLD = 100


async def filter_professional_sellers(
    items,
    blacklist,
    seller_cache,
    item_seller_cache,
    seller_name_cache,
    context,
    check_enabled=True
):
    """
    并发检查卖家是否为专业商家，同时应用黑名单和昵称规则。
    返回过滤后的商品列表。
    """
    if not check_enabled or not items:
        return items

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    tasks = [
        _check_single_item(
            item, blacklist, seller_cache, item_seller_cache,
            seller_name_cache, context, semaphore
        )
        for item in items
    ]
    results = await asyncio.gather(*tasks)
    filtered = [item for item, keep in results if keep]
    logger.info(f"过滤完成：保留 {len(filtered)} 个，过滤 {len(items)-len(filtered)} 个")
    return filtered


async def _check_single_item(
    item, blacklist, seller_cache, item_seller_cache,
    seller_name_cache, context, semaphore
):
    async with semaphore:
        link = item.get("link")
        if not link:
            return item, False

        seller_id = item.get("seller_id")
        seller_name = item.get("seller_name")

        # 1. 如果已有 seller_id，走专业商家检查流程
        if seller_id:
            if seller_id in seller_cache:
                return item, not seller_cache[seller_id]
            if seller_id in blacklist:
                seller_cache[seller_id] = True
                return item, False

            seller_url = f"https://www.goofish.com/personal?userId={seller_id}"
            is_pro = await _is_professional_seller(context, seller_url)
            seller_cache[seller_id] = is_pro
            if is_pro:
                blacklist.add(seller_id)
                logger.info(f"卖家 {seller_id} 判定为专业商家，过滤: {item['title'][:30]}")
                return item, False
            else:
                logger.info(f"卖家 {seller_id} 非专业商家，保留")
                return item, True

        # 2. 没有 seller_id 但有 seller_name，根据昵称规则和黑名单过滤
        if seller_name and str(seller_name).strip():
            name = str(seller_name).strip()
            # 纯数字昵称直接过滤
            if name.isdigit():
                logger.info(f"纯数字昵称，过滤: {item['title'][:30]}")
                return item, False
            # 昵称在黑名单中
            if name in blacklist:
                logger.info(f"昵称 {name} 在黑名单中，过滤: {item['title'][:30]}")
                return item, False
            # 昵称正常且不在黑名单，保留
            return item, True

        # 3. 既没有 seller_id 也没有 seller_name，过滤
        logger.warning(f"无卖家信息，过滤: {item['title'][:30]}")
        return item, False


async def _get_seller_info_from_item(context, item_url):
    """
    备用：打开商品详情页获取卖家ID和昵称。
    此函数当前可能不被调用，但保留以支持后续扩展。
    """
    page = await context.new_page()
    seller_id = None
    seller_name = None
    seller_url = None
    login_user_id = None
    seller_event = asyncio.Event()

    seller_selectors = [
        "a[href*='personal?userId=']",
        "a[href*='userId=']",
        "a[href*='/personal']",
        "div[class*='item-user'] a[href*='userId=']",
        "div[class*='user-info'] a[href*='userId=']",
    ]

    async def handle_response(response):
        nonlocal seller_id, seller_name, seller_url, login_user_id
        try:
            if response.request.resource_type not in ("xhr", "fetch"):
                return

            if LOGIN_USER_API_PATTERN in response.url:
                try:
                    data = await response.json()
                    if "data" in data and "userId" in data["data"]:
                        login_user_id = str(data["data"]["userId"])
                except:
                    pass
                return

            try:
                data = await response.json()
            except:
                return

            def find_seller_id(obj):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k == "sellerId" and isinstance(v, (str, int)):
                            return str(v)
                        res = find_seller_id(v)
                        if res:
                            return res
                elif isinstance(obj, list):
                    for item in obj:
                        res = find_seller_id(item)
                        if res:
                            return res
                return None

            candidate = find_seller_id(data)
            if candidate and not seller_id and candidate != login_user_id:
                seller_id = candidate
                seller_url = f"https://www.goofish.com/personal?userId={seller_id}"

                def find_nick(obj):
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if k in ("nick", "nickName", "sellerNick") and isinstance(v, str):
                                return v
                            res = find_nick(v)
                            if res:
                                return res
                    elif isinstance(obj, list):
                        for item in obj:
                            res = find_nick(item)
                            if res:
                                return res
                    return None

                seller_name = find_nick(data)
                seller_event.set()
        except:
            pass

    page.on("response", handle_response)

    try:
        await page.goto(item_url, wait_until="domcontentloaded", timeout=8000)
        try:
            await asyncio.wait_for(seller_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pass

        if not seller_id:
            for selector in seller_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        href = await element.get_attribute("href")
                        if href:
                            m = re.search(r'userId=(\d+)', href)
                            if m:
                                seller_id = m.group(1)
                                seller_url = f"https://www.goofish.com/personal?userId={seller_id}"
                                try:
                                    seller_name = (await element.inner_text()).strip() or None
                                except:
                                    pass
                                break
                except:
                    continue

        if not seller_id:
            html = await page.content()
            m = re.search(r'personal\?userId=(\d+)', html)
            if m:
                seller_id = m.group(1)
                seller_url = f"https://www.goofish.com/personal?userId={seller_id}"

        if not seller_id:
            return None, None, None

        if not seller_name:
            seller_name = seller_id

        return seller_id, seller_name, seller_url
    except Exception as e:
        logger.error(f"获取卖家信息失败 {item_url}: {e}")
        return None, None, None
    finally:
        await page.close()


async def _is_professional_seller(context, seller_url):
    """
    访问卖家主页，提取“在售”数量，若提取失败则尝试提取“卖出”数量。
    只要其中任一数量超过对应阈值，就判定为专业商家。
    """
    page = await context.new_page()
    try:
        await page.goto(seller_url, wait_until="domcontentloaded", timeout=CHECK_SELLER_TIMEOUT)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except:
            pass

        on_sale_count = await _extract_count_by_label(page, "在售")
        if on_sale_count is not None:
            logger.info(f"从卖家主页提取在售商品数: {on_sale_count}")
            return on_sale_count > SELLER_ITEM_COUNT_THRESHOLD

        sold_count = await _extract_count_by_label(page, "卖出")
        if sold_count is not None:
            logger.info(f"未能提取在售数量，但提取到卖出商品数: {sold_count}")
            if sold_count > SELL_COUNT_THRESHOLD:
                logger.info("卖出数量超过阈值，判定为专业商家")
                return True
            else:
                logger.info("卖出数量未超过阈值，视为非专业商家")
                return False

        logger.warning("未能提取在售/卖出数量，视为非专业商家")
        return False
    except Exception as e:
        logger.error(f"检查专业商家失败: {e}")
        return False
    finally:
        await page.close()


async def _extract_count_by_label(page, label):
    """
    从页面中提取包含指定标签（如“在售”、“卖出”）的数字。
    返回 int，若失败返回 None。
    """
    selectors = [
        f"div:has-text('{label}')",
        f"span:has-text('{label}')",
        f"[class*='tabItem']:has-text('{label}')",
    ]
    for sel in selectors:
        try:
            locator = page.locator(sel).first
            if await locator.count() > 0:
                text = await locator.inner_text()
                m = re.search(rf'{label}\s*[:：]?\s*(\d+)', text)
                if m:
                    return int(m.group(1))
        except:
            continue

    try:
        body_text = await page.inner_text("body")
        for line in body_text.splitlines():
            if label in line:
                m = re.search(rf'{label}\s*[:：]?\s*(\d+)', line)
                if m:
                    return int(m.group(1))
    except:
        pass

    try:
        count = await page.evaluate(f"""
            () => {{
                const all = document.querySelectorAll('*');
                for (const el of all) {{
                    const ownText = Array.from(el.childNodes)
                        .filter(node => node.nodeType === Node.TEXT_NODE)
                        .map(node => node.textContent.trim())
                        .join(' ');
                    if (ownText.includes('{label}')) {{
                        const m = ownText.match(/{label}\\s*[:：]?\\s*(\\d+)/);
                        if (m) return parseInt(m[1], 10);
                    }}
                }}
                return null;
            }}
        """)
        if count is not None:
            return int(count)
    except:
        pass

    return None