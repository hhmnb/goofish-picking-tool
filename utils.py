# utils.py
import re

def extract_item_id(link: str) -> str:
    """从商品链接提取商品ID"""
    if not link:
        return link
    match = re.search(r'[?&]id=(\d+)', link)
    return match.group(1) if match else link

def extract_seller_id(url: str) -> str:
    """从卖家主页链接提取卖家ID"""
    if not url:
        return None
    m = re.search(r'userId=(\d+)', url)
    if m:
        return m.group(1)
    m = re.search(r'/user/(\d+)', url)
    if m:
        return m.group(1)
    return None

def extract_number(text: str) -> int:
    """提取文本中的第一个数字"""
    if not text:
        return None
    m = re.search(r'(\d+)', text)
    return int(m.group(1)) if m else None

def normalize_link(href: str) -> str:
    """将相对链接转为绝对链接"""
    if href.startswith("//"):
        return "https:" + href
    elif href.startswith("/"):
        return "https://www.goofish.com" + href
    return href