"""
Browser MCP Server — FastMCP + Playwright
端口 8201, streamable-http 传输

为 MarketAgent / ReviewInsightAgent 提供:
  - amzn_search: 搜索 Amazon 商品
  - amzn_product: 获取商品详情 (标题/价格/Rating/BSR/评论数)
  - amzn_reviews: 抓取商品评论
  - web_fetch: 通用网页抓取

启动: python mcp_servers/browser_scraper.py
需要: pip install playwright && python -m playwright install chromium
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import FastMCP

logger = __import__("create_logger").get_logger("browser_mcp")
mcp = FastMCP("Browser Scraper MCP", version="1.0.0")

# Playwright 可用性检测
_playwright_available = False
try:
    from playwright.sync_api import sync_playwright
    _playwright_available = True
except ImportError:
    pass


def _get_page():
    if not _playwright_available:
        raise RuntimeError("Playwright not installed: pip install playwright && playwright install chromium")
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    return ctx.new_page(), browser, pw


@mcp.tool()
def amzn_search(keyword: str, max_results: int = 10) -> dict:
    """搜索 Amazon.com 商品。输入搜索关键词，返回商品列表（ASIN/标题/价格/Rating/评论数）。

    参数:
        keyword: 搜索关键词 (如 "desk fan")
        max_results: 最大返回数量 (默认10)
    """
    if not _playwright_available:
        return {"error": "Playwright not installed", "fallback": True, "products": []}

    try:
        page, browser, pw = _get_page()
        url = f"https://www.amazon.com/s?k={keyword.replace(' ', '+')}"
        page.goto(url, wait_until="domcontentloaded", timeout=15000)

        products = page.evaluate("""(max) => {
            const items = document.querySelectorAll('[data-component-type="s-search-result"]');
            const results = [];
            for (let i = 0; i < Math.min(items.length, max); i++) {
                const el = items[i];
                const title = el.querySelector('h2 span')?.textContent?.trim() || '';
                const pw = el.querySelector('.a-price-whole')?.textContent?.trim() || '';
                const pf = el.querySelector('.a-price-fraction')?.textContent?.trim() || '';
                const rating = el.querySelector('.a-icon-alt')?.textContent?.trim() || '';
                const reviews = el.querySelector('.a-size-base.s-underline-text')?.textContent?.trim() || '';
                const asin = el.getAttribute('data-asin') || '';
                results.push({ asin, title, price: pw + (pf ? '.' + pf : ''), rating, reviews });
            }
            return results;
        }""", max_results)

        page.close()
        browser.close()
        pw.stop()
        return {"keyword": keyword, "source": "Amazon.com", "total": len(products), "products": products}
    except Exception as e:
        logger.error("amzn_search error: %s", e)
        return {"error": str(e), "fallback": True, "products": []}


@mcp.tool()
def amzn_product(asin: str) -> dict:
    """获取 Amazon 商品详情页：标题、价格、Rating、Best Seller Rank、评论数。

    参数:
        asin: Amazon ASIN (如 B07XLPRM9M)
    """
    if not _playwright_available:
        return {"error": "Playwright not installed", "fallback": True}

    try:
        page, browser, pw = _get_page()
        url = f"https://www.amazon.com/dp/{asin}"
        page.goto(url, wait_until="domcontentloaded", timeout=15000)

        data = page.evaluate("""() => {
            const title = document.getElementById('productTitle')?.textContent?.trim() || '';
            const price = document.querySelector('.a-price .a-offscreen')?.textContent?.trim() || '';
            const rating = document.getElementById('acrPopover')?.title?.trim() || '';
            const reviews = document.getElementById('acrCustomerReviewText')?.textContent?.trim() || '';
            const bsr = document.querySelector('#detailBullets_feature_div')?.textContent?.trim() || '';
            return { title, price, rating, reviews, bsr_short: bsr.slice(0, 500) };
        }""")

        page.close()
        browser.close()
        pw.stop()
        return {"asin": asin, **data}
    except Exception as e:
        return {"error": str(e), "fallback": True}


@mcp.tool()
def amzn_reviews(asin: str, max_reviews: int = 20) -> dict:
    """抓取 Amazon 商品评论列表（标题/评分/正文/日期）。

    参数:
        asin: Amazon ASIN
        max_reviews: 最大评论数 (默认20)
    """
    if not _playwright_available:
        return {"error": "Playwright not installed", "fallback": True, "reviews": []}

    try:
        page, browser, pw = _get_page()
        url = f"https://www.amazon.com/product-reviews/{asin}"
        page.goto(url, wait_until="domcontentloaded", timeout=15000)

        reviews = page.evaluate("""(max) => {
            const items = document.querySelectorAll('[data-hook="review"]');
            const results = [];
            for (let i = 0; i < Math.min(items.length, max); i++) {
                const el = items[i];
                const title = el.querySelector('[data-hook="review-title"] span:last-child')?.textContent?.trim() || '';
                const rating = el.querySelector('[data-hook="review-star-rating"] span:last-child')?.textContent?.trim() || '';
                const body = el.querySelector('[data-hook="review-body"] span')?.textContent?.trim() || '';
                const date = el.querySelector('[data-hook="review-date"]')?.textContent?.trim() || '';
                results.push({ title, rating, body, date });
            }
            return results;
        }""", max_reviews)

        page.close()
        browser.close()
        pw.stop()
        return {"asin": asin, "source": "Amazon.com", "total": len(reviews), "reviews": reviews}
    except Exception as e:
        return {"error": str(e), "fallback": True, "reviews": []}


@mcp.tool()
def web_fetch(url: str, selector: str = "") -> dict:
    """通用网页内容抓取（纯文本提取，无JS渲染）。

    参数:
        url: 目标URL
        selector: CSS选择器 (可选, 为空则提取全文)
    """
    import httpx
    try:
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ProductScout/1.0)"},
                         timeout=15, follow_redirects=True)
        text = resp.text[:50000]
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return {"url": url, "length": len(text), "text": text[:5000]}
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    logger.info("Browser MCP Server starting on :8201 (streamable-http)")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8201, path="/mcp")
