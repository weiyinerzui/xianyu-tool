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
from app.services.scorer import calc_want_velocity

logger = logging.getLogger(__name__)


class CrawlerService:
    """采集服务。"""

    def __init__(self) -> None:
        self.httpx_crawler = HttpxCrawler()
        self.playwright_crawler = PlaywrightCrawler()
        # 最近一次采集失败原因（供 API 层回显，避免静默失败）
        self.last_error: str = ""

    async def crawl(
        self,
        keyword: str,
        category: str | None = None,
        db: AsyncSession | None = None,
    ) -> tuple[list[CrawledProduct], str]:
        """执行采集，返回 (商品列表, 使用的采集器名)。

        L1 → L2 降级策略：
        - L1 彻底失败 → L2 全量采集
        - L1 成功但想要数全 0 → 数据残缺（服务端已停发 wantNum），
          继续 L2 采集拿完整数据（L2 会从 DOM 回填想要数）
        """
        # L1: httpx
        try:
            products = await self.httpx_crawler.search(keyword, category)
            if products:
                all_zero_want = all(p.want_count == 0 for p in products)
                if not all_zero_want:
                    logger.info("L1 success: %d products for '%s'", len(products), keyword)
                    if db:
                        await self._save_products(products, keyword, db)
                    return products, "httpx"
                logger.info(
                    "L1 拿到 %d 条但想要数全 0（服务端停发 wantNum），升级到 L2",
                    len(products),
                )
                self.last_error = ""
        except Exception as e:
            logger.warning("L1 failed for '%s': %s", keyword, e)
            self.last_error = f"L1 httpx 失败：{e}"

        # L2: Playwright
        try:
            logger.info("Falling back to L2 for '%s'", keyword)
            products = await self.playwright_crawler.search(keyword, category)
            if products:
                if db:
                    await self._save_products(products, keyword, db)
                return products, "playwright"
            self.last_error = "L2 Playwright 未取到数据（可能未登录或被风控）"
        except Exception as e:
            logger.error("L2 failed for '%s': %s", keyword, e)
            self.last_error = str(e)

        logger.error("All levels failed for '%s': %s", keyword, self.last_error)
        return [], "none"

    async def _save_products(
        self, products: list[CrawledProduct], keyword: str, db: AsyncSession
    ) -> int:
        """保存采集结果到数据库（增量，按 xianyu_id 去重）。

        同时写入快照表（P1-1），为「想要数增速」提供时序数据。
        快照必须在本轮算分之前写入：算分需要读「上一条」快照，
        所以先落本轮快照、再查上一条，避免把当前值当成历史值。
        """
        from app.models.snapshot import ProductSnapshot

        new_count = 0
        now = datetime.utcnow()

        for cp in products:
            if not cp.xianyu_id:
                continue

            # 读取上一条快照（用于算增速），再写入本轮快照
            prev_stmt = (
                select(ProductSnapshot)
                .where(ProductSnapshot.xianyu_id == cp.xianyu_id)
                .order_by(ProductSnapshot.captured_at.desc())
                .limit(1)
            )
            prev = (await db.execute(prev_stmt)).scalar_one_or_none()
            prev_want = prev.want_count if prev else None
            prev_at = prev.captured_at if prev else None

            # 检查商品是否已存在
            stmt = select(Product).where(Product.xianyu_id == cp.xianyu_id)
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # 更新动态字段，并写入快照
                existing.want_count = cp.want_count
                existing.price = cp.price
                existing.fetched_at = now
                target = existing
            else:
                target = Product(
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
                db.add(target)
                new_count += 1

            db.add(ProductSnapshot(
                xianyu_id=cp.xianyu_id,
                want_count=cp.want_count,
                view_count=cp.view_count,
                price=cp.price,
                captured_at=now,
            ))

            # 有历史快照时立刻算增速（权重最高的维度）
            if prev_want is not None and prev_at is not None:
                hours = max((now - prev_at).total_seconds() / 3600.0, 0.01)
                target.want_velocity = calc_want_velocity(cp.want_count, prev_want, hours)

        await db.commit()
        logger.info("Saved %d new products + snapshots for '%s'", new_count, keyword)
        return new_count


# 模块级单例
_crawler_service: CrawlerService | None = None


def get_crawler_service() -> CrawlerService:
    global _crawler_service
    if _crawler_service is None:
        _crawler_service = CrawlerService()
    return _crawler_service
