"""L1 采集器：httpx 直请求闲鱼搜索 API。

参考 xianyu-tool/backend/app/crawlers/httpx_crawler.py 的多 URL 降级策略，
解析器使用 base.parse_search_api_json（源自 ai-goofish-monitor）。
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from app.crawlers.base import BaseCrawler, CrawledProduct, parse_search_api_json

logger = logging.getLogger(__name__)


class HttpxCrawler(BaseCrawler):
    """L1: 直接 HTTP 请求闲鱼搜索接口。"""

    SEARCH_API = "https://h5api.m.goofish.com/h5/mtop.taobao.idle.awesome.post.search/1.0/"
    WEB_SEARCH = "https://www.goofish.com/search"

    async def search(self, keyword: str, category: str | None = None) -> list[CrawledProduct]:
        headers = {
            "User-Agent": self.random_ua(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.goofish.com/",
        }

        try:
            async with httpx.AsyncClient(
                timeout=15.0, follow_redirects=True, trust_env=False
            ) as client:
                # 尝试 mtop 搜索 API
                products = await self._try_mtop_api(client, keyword, category, headers)
                if products:
                    logger.info("HttpxCrawler(mtop): %d products for '%s'", len(products), keyword)
                    return products

                # 尝试 web 搜索页
                products = await self._try_web_search(client, keyword, category, headers)
                if products:
                    logger.info("HttpxCrawler(web): %d products for '%s'", len(products), keyword)
                    return products
        except Exception as e:
            logger.warning("HttpxCrawler error for '%s': %s", keyword, e)
            self._consecutive_failures += 1
            raise

        logger.warning("HttpxCrawler: no data for '%s'", keyword)
        return []

    async def _try_mtop_api(
        self,
        client: httpx.AsyncClient,
        keyword: str,
        category: str | None,
        headers: dict[str, str],
    ) -> list[CrawledProduct]:
        try:
            params: dict[str, Any] = {
                "q": keyword,
                "jsv": "2.7.2",
                "appKey": "34839810",
                "type": "originaljson",
                "dataType": "json",
                "v": "1.0",
            }
            resp = await client.get(self.SEARCH_API, params=params, headers=headers)
            if resp.status_code != 200:
                return []
            data = resp.json()
            # 检查风控标记
            ret = data.get("ret", [])
            if any("RGV587" in str(r) or "FAIL_SYS" in str(r) for r in ret):
                logger.warning("HttpxCrawler: 风控触发 %s", ret)
                return []
            return parse_search_api_json(data, category or "")
        except Exception as e:
            logger.debug("mtop API failed: %s", e)
            return []

    async def _try_web_search(
        self,
        client: httpx.AsyncClient,
        keyword: str,
        category: str | None,
        headers: dict[str, str],
    ) -> list[CrawledProduct]:
        try:
            resp = await client.get(
                self.WEB_SEARCH, params={"q": quote(keyword)}, headers=headers
            )
            if resp.status_code != 200:
                return []
            # web 页返回 HTML，尝试提取内嵌 JSON
            text = resp.text
            return self._extract_json_from_html(text, category or "")
        except Exception as e:
            logger.debug("web search failed: %s", e)
            return []

    def _extract_json_from_html(self, html: str, category: str) -> list[CrawledProduct]:
        """从 HTML 中提取内嵌的搜索结果 JSON。"""
        import json
        import re

        # 闲鱼 web 页常把数据放在 __NEXT_DATA__ 或 window.__INITIAL_STATE__
        patterns = [
            r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});",
            r"window\.__NUXT__\s*=\s*(\{.*?\});",
        ]
        for pattern in patterns:
            m = re.search(pattern, html, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1))
                    products = parse_search_api_json(data, category)
                    if products:
                        return products
                except (json.JSONDecodeError, ValueError):
                    continue
        return []
