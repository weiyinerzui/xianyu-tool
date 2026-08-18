"""采集服务：两级降级 + 数据存储。

L1: httpx 直请求（快，但可能被风控）
L2: Playwright 浏览器（慢，但抗风控）
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawlers.base import CrawledProduct
from app.crawlers.httpx_crawler import HttpxCrawler
from app.crawlers.playwright_crawler import PlaywrightCrawler
from app.models.product import Product

logger = logging.getLogger(__name__)


class CrawlerService:
    """采集服务。"""

    def __init__(self) -> None:
        self.httpx_crawler = HttpxCrawler()
        self.playwright_crawler = PlaywrightCrawler()

    async def crawl(
        self,
        keyword: str,
        category: str | None = None,
        db: AsyncSession | None = None,
    ) -> tuple[list[CrawledProduct], str]:
        """执行采集，返回 (商品列表, 使用的采集器名)。

        L1 → L2 降级策略。
        """
        # L1: httpx
        try:
            products = await self.httpx_crawler.search(keyword, category)
            if products:
                logger.info("L1 success: %d products for '%s'", len(products), keyword)
                if db:
                    await self._save_products(products, keyword, db)
                return products, "httpx"
        except Exception as e:
            logger.warning("L1 failed for '%s': %s", keyword, e)

        # L2: Playwright
        try:
            logger.info("Falling back to L2 for '%s'", keyword)
            products = await self.playwright_crawler.search(keyword, category)
            if products:
                if db:
                    await self._save_products(products, keyword, db)
                return products, "playwright"
        except Exception as e:
            logger.error("L2 failed for '%s': %s", keyword, e)

        logger.error("All levels failed for '%s'", keyword)
        return [], "none"

    async def _save_products(
        self, products: list[CrawledProduct], keyword: str, db: AsyncSession
    ) -> int:
        """保存采集结果到数据库（增量，按 xianyu_id 去重）。"""
        new_count = 0
        for cp in products:
            if not cp.xianyu_id:
                continue
            # 检查是否已存在
            stmt = select(Product).where(Product.xianyu_id == cp.xianyu_id)
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # 更新想要数等动态字段
                existing.want_count = cp.want_count
                existing.price = cp.price
                existing.fetched_at = datetime.utcnow()
            else:
                product = Product(
                    xianyu_id=cp.xianyu_id,
                    title=cp.title,
                    price=cp.price,
                    original_price=cp.original_price,
                    want_count=cp.want_count,
                    view_count=cp.view_count,
                    seller_name=cp.seller_name,
                    seller_level=cp.seller_level,
                    area=cp.area,
                    category=cp.category,
                    tags={"tags": cp.tags} if cp.tags else None,
                    image_url=cp.image_url,
                    link=cp.link,
                    publish_time=cp.publish_time,
                    source="search",
                    keyword=keyword,
                )
                db.add(product)
                new_count += 1

        await db.commit()
        logger.info("Saved %d new products for '%s'", new_count, keyword)
        return new_count


# 模块级单例
_crawler_service: CrawlerService | None = None


def get_crawler_service() -> CrawlerService:
    global _crawler_service
    if _crawler_service is None:
        _crawler_service = CrawlerService()
    return _crawler_service
