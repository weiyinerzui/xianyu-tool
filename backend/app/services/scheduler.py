"""定时采集服务（APScheduler）。

功能：
- 按关键词列表定时触发采集（默认每 4 小时）
- 增量更新（按 xianyu_id 去重）
- 采集前检查风控熔断状态，熔断期间跳过
- 采集后更新商品热度分
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings

logger = logging.getLogger(__name__)

# 默认采集关键词（虚拟商品方向）
DEFAULT_KEYWORDS = [
    "考研资料",
    "Python教程",
    "英语学习资料",
    "软件教程",
    "学习笔记",
]


class SchedulerService:
    """定时采集调度器。"""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._keywords: list[str] = list(DEFAULT_KEYWORDS)
        self._started = False

    @property
    def keywords(self) -> list[str]:
        return list(self._keywords)

    def set_keywords(self, keywords: list[str]) -> None:
        self._keywords = list(keywords)

    def add_keyword(self, keyword: str) -> None:
        if keyword and keyword not in self._keywords:
            self._keywords.append(keyword)

    def remove_keyword(self, keyword: str) -> None:
        if keyword in self._keywords:
            self._keywords.remove(keyword)

    async def _crawl_job(self) -> dict[str, Any]:
        """单次采集任务（采集所有关键词）。"""
        from app.database import async_session
        from app.services.crawler_service import get_crawler_service
        from app.services.guard import get_guard
        from app.services.scorer import calculate_hot_score, calc_category_avg_price

        guard = get_guard()
        if guard.is_tripped("crawl"):
            logger.warning("采集跳过：风控熔断中，剩余 %ds", guard.remaining("crawl"))
            return {"skipped": True, "reason": "circuit_tripped"}

        service = get_crawler_service()
        results: list[dict[str, Any]] = []

        for kw in self._keywords:
            try:
                async with async_session() as db:
                    products, source = await service.crawl(kw, None, db)
                    results.append({
                        "keyword": kw,
                        "source": source,
                        "total": len(products),
                    })

                    # 更新热度分
                    if products:
                        prices = [p.price for p in products if p.price > 0]
                        avg_price = calc_category_avg_price(prices)
                        from sqlalchemy import select
                        from app.models.product import Product

                        for p in products:
                            stmt = select(Product).where(Product.xianyu_id == p.xianyu_id)
                            row = (await db.execute(stmt)).scalar_one_or_none()
                            if row:
                                scores = calculate_hot_score(
                                    current_want=row.want_count,
                                    previous_want=None,
                                    hours=0,
                                    price=row.price,
                                    category_avg_price=avg_price,
                                    want_count=row.want_count,
                                    view_count=row.view_count,
                                    publish_time=row.publish_time,
                                    total_listings=len(products),
                                )
                                row.hot_score = scores["hot_score"]
                                row.want_velocity = scores["want_velocity"]
                                row.price_advantage = scores["price_advantage"]
                                row.engagement_rate = scores["engagement_rate"]
                                row.freshness = scores["freshness"]
                                row.competition = scores["competition"]
                        await db.commit()

            except Exception as e:
                logger.error("采集 '%s' 失败: %s", kw, e)
                # 检测是否风控
                if "RGV587" in str(e) or "FAIL_SYS" in str(e):
                    guard.trip("crawl")
                    logger.error("触发风控熔断")
                results.append({"keyword": kw, "error": str(e)})

        logger.info("采集任务完成: %s", results)
        return {"skipped": False, "results": results, "finished_at": datetime.utcnow().isoformat()}

    def start(self, interval_hours: int = 4) -> None:
        """启动定时采集。"""
        if self._started:
            return

        self._scheduler.add_job(
            self._crawl_job,
            trigger=IntervalTrigger(hours=interval_hours),
            id="crawl_job",
            replace_existing=True,
            next_run_time=datetime.utcnow(),  # 启动后立即执行一次
        )
        self._scheduler.start()
        self._started = True
        logger.info("定时采集已启动，间隔 %d 小时", interval_hours)

    def stop(self) -> None:
        """停止定时采集。"""
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
            logger.info("定时采集已停止")

    def status(self) -> dict[str, Any]:
        """调度器状态。"""
        jobs = self._scheduler.get_jobs() if self._started else []
        return {
            "running": self._started,
            "keywords": self._keywords,
            "jobs": [
                {
                    "id": j.id,
                    "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
                }
                for j in jobs
            ],
        }

    async def run_once(self) -> dict[str, Any]:
        """手动触发一次采集。"""
        return await self._crawl_job()


# 模块级单例
_scheduler: SchedulerService | None = None


def get_scheduler() -> SchedulerService:
    global _scheduler
    if _scheduler is None:
        _scheduler = SchedulerService()
    return _scheduler
