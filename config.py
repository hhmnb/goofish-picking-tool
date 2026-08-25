# config.py
from pathlib import Path

# ---------- 路径配置 ----------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
USER_DATA_DIR = DATA_DIR / "browser_data"
RESULT_DIR = DATA_DIR / "results"
RESULT_FILE = RESULT_DIR / "latest.tsv"
TEMPLATE_FILE = DATA_DIR / "提示词.txt"
BLACKLIST_FILE = DATA_DIR / "seller_blacklist.txt"
LOG_FILE = DATA_DIR / "app.log"

# 自动创建目录
for path in [DATA_DIR, RESULT_DIR, USER_DATA_DIR]:
    path.mkdir(parents=True, exist_ok=True)

# ---------- 爬虫配置 ----------
BASE_URL = "https://www.goofish.com/search?q={keyword}"
DETAIL_API_PATTERN = "mtop.taobao.idle.pc.detail"
LOGIN_USER_API_PATTERN = "loginuser.get"
VIEWPORT = {"width": 1280, "height": 900}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
BROWSER_ARGS = ["--disable-blink-features=AutomationControlled"]

# 翻页按钮选择器（仅保留有效的一个）
NEXT_PAGE_SELECTORS = [
    "button[class*='search-pagination-arrow-container']:has(div[class*='search-pagination-arrow-right'])",
    "div[class*='search-pagination-arrow-right'] >> xpath=..",
]

# 翻页输入框及按钮选择器
PAGE_JUMP_INPUT = "[class*='search-pagination-to-page-container'] input"
PAGE_JUMP_BTN = "[class*='search-pagination-to-page-container'] button"

# ---------- 专业商家过滤配置 ----------
SELLER_ITEM_COUNT_THRESHOLD = 20          # 在售商品数阈值
CHECK_SELLER_TIMEOUT = 30000              # 超时(毫秒)
MAX_CONCURRENCY = 4                       # 异步并发检查卖家数量

# ---------- GUI 颜色主题 ----------
BG_DEEP_BLUE = "#0A192F"
BG_CONTAINER = "#172A45"
TEXT_WHITE = "#E6F1FF"
TEXT_CYAN = "#64FFDA"
BTN_BLUE = "#0052CC"
BTN_GREEN = "#28a745"
BTN_ORANGE = "#FF8C00"