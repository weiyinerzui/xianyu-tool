"""L2 采集器：Playwright 浏览器自动化（抗风控降级方案）。

参考 goofish-cli commands/search/search.py 的 DOM 提取思路，
以及 xianyu-tool/backend/app/crawlers/playwright_crawler.py 的持久化上下文。
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

from app.crawlers.base import BaseCrawler, CrawledProduct, parse_price_str

logger = logging.getLogger(__name__)

# 页面内执行的 JS：提取搜索结果卡片
_EXTRACT_JS = r"""
(limit) => (async () => {
  const wait = (ms) => new Promise(r => setTimeout(r, ms));
  const waitFor = async (predicate, timeoutMs = 8000) => {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (predicate()) return true;
      await wait(150);
    }
    return false;
  };
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const sel = {
    card: 'a[href*="/item?id="]',
    title: '[class*="row1-wrap-title"], [class*="main-title"]',
    priceWrap: '[class*="price-wrap"]',
    priceNum: '[class*="number"]',
    priceDec: '[class*="decimal"]',
    sellerWrap: '[class*="row4-wrap-seller"]',
    sellerText: '[class*="seller-text"]',
  };
  await waitFor(() => {
    const t = document.body?.innerText || '';
    return Boolean(
      document.querySelector(sel.card)
      || /请先登录|登录后|验证码|安全验证|暂无相关宝贝/.test(t)
    );
  });
  const items = Array.from(document.querySelectorAll(sel.card))
    .slice(0, limit)
    .map((card) => {
      const href = card.href || card.getAttribute('href') || '';
      const title = clean(card.querySelector(sel.title)?.textContent || '');
      const pw = card.querySelector(sel.priceWrap);
      const pn = clean(pw?.querySelector(sel.priceNum)?.textContent || '');
      const pd = clean(pw?.querySelector(sel.priceDec)?.textContent || '');
      const loc = clean(card.querySelector(sel.sellerWrap)?.querySelector(sel.sellerText)?.textContent || '');
      return { title, url: href, price: clean('¥' + pn + pd).replace(/^¥\s*$/, ''), location: loc };
    });
  return { items, empty: /暂无相关宝贝|没有找到/.test(document.body?.innerText || '') };
});
"""


def _item_id_from_url(url: str) -> str:
    m = re.search(r"[?&]id=(\d+)", url or "")
    return m.group(1) if m else ""


class PlaywrightCrawler(BaseCrawler):
    """L2: Playwright 浏览器采集，抗风控。"""

    async def search(self, keyword: str, category: str | None = None) -> list[CrawledProduct]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright not installed")
            return []

        products: list[CrawledProduct] = []
        url = f"https://www.goofish.com/search?q={quote(keyword)}"

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-gpu", "--disable-blink-features=AutomationControlled"],
                )
                context = await browser.new_context(
                    user_agent=self.random_ua(),
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                )
                page = await context.new_page()

                # 拦截搜索 API 响应（优先用 API JSON，字段更全）
                api_products: list[CrawledProduct] = []

                async def on_response(response):
                    nonlocal api_products
                    if "mtop.taobao.idle.awesome.post.search" in response.url:
                        try:
                            data = await response.json()
                            from app.crawlers.base import parse_search_api_json
                            parsed = parse_search_api_json(data, category or "")
                            if parsed:
                                api_products.extend(parsed)
                        except Exception:
                            pass

                page.on("response", on_response)

                await page.goto(url, wait_until="networkidle", timeout=20000)
                await page.wait_for_timeout(2000)

                # 优先用 API 拦截到的数据
                if api_products:
                    logger.info("PlaywrightCrawler(API拦截): %d products", len(api_products))
                    products = api_products
                else:
                    # 降级到 DOM 提取
                    payload = await page.evaluate(_EXTRACT_JS, 30)
                    items = payload.get("items", []) if isinstance(payload, dict) else []
                    for it in items:
                        products.append(CrawledProduct(
                            xianyu_id=_item_id_from_url(it.get("url", "")),
                            title=it.get("title", ""),
                            price=parse_price_str(it.get("price", "")),
                            area=it.get("location", ""),
                            link=it.get("url", ""),
                            category=category or "",
                        ))
                    logger.info("PlaywrightCrawler(DOM): %d products", len(products))

                await browser.close()
        except Exception as e:
            logger.error("PlaywrightCrawler failed for '%s': %s", keyword, e)
            self._consecutive_failures += 1
            raise

        return products
