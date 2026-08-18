"""数据看板服务：趋势分析 + 统计汇总。

基于已采集的商品数据，提供：
- 价格分布直方图
- 想要数分布
- 热门关键词排行
- 类目分布
- 时间趋势（按发布时间分桶）
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import desc, func, select

from app.database import async_session
from app.models.product import Product
from app.services.scorer import calc_category_avg_price


class DashboardService:
    """数据看板服务。"""

    async def overview(self, keyword: str | None = None) -> dict[str, Any]:
        """总览统计。"""
        async with async_session() as db:
            query = select(Product)
            if keyword:
                query = query.where(Product.title.ilike(f"%{keyword}%"))
            rows = (await db.execute(query)).scalars().all()

        if not rows:
            return {"total": 0}

        prices = [r.price for r in rows if r.price > 0]
        wants = [r.want_count for r in rows]
        scores = [r.hot_score for r in rows]

        return {
            "total": len(rows),
            "price": {
                "avg": round(calc_category_avg_price(prices), 2),
                "min": min(prices) if prices else 0,
                "max": max(prices) if prices else 0,
                "median": sorted(prices)[len(prices) // 2] if prices else 0,
            },
            "want_count": {
                "avg": round(sum(wants) / len(wants), 1) if wants else 0,
                "max": max(wants) if wants else 0,
                "total": sum(wants),
            },
            "hot_score": {
                "avg": round(sum(scores) / len(scores), 1) if scores else 0,
                "max": max(scores) if scores else 0,
            },
            "sellers": len({r.seller_name for r in rows if r.seller_name}),
            "categories": len({r.category for r in rows if r.category}),
        }

    async def price_distribution(self, keyword: str | None = None, bins: int = 10) -> dict[str, Any]:
        """价格分布直方图。"""
        async with async_session() as db:
            query = select(Product.price)
            if keyword:
                query = query.where(Product.title.ilike(f"%{keyword}%"))
            rows = (await db.execute(query)).scalars().all()

        prices = [p for p in rows if p and p > 0]
        if not prices:
            return {"bins": [], "total": 0}

        min_p, max_p = min(prices), max(prices)
        if max_p == min_p:
            return {"bins": [{"label": f"{min_p:.0f}", "count": len(prices)}], "total": len(prices)}

        step = (max_p - min_p) / bins
        histogram = []
        for i in range(bins):
            low = min_p + i * step
            high = low + step
            count = sum(1 for p in prices if low <= p < high)
            histogram.append({
                "label": f"{low:.0f}-{high:.0f}",
                "count": count,
            })
        # 最后一个 bin 包含上界
        histogram[-1]["count"] = sum(1 for p in prices if min_p + (bins - 1) * step <= p <= max_p)

        return {"bins": histogram, "total": len(prices)}

    async def top_products(self, sort_by: str = "hot_score", limit: int = 20) -> dict[str, Any]:
        """热门商品排行。"""
        async with async_session() as db:
            if sort_by == "want_count":
                query = select(Product).order_by(desc(Product.want_count))
            elif sort_by == "price_asc":
                query = select(Product).order_by(Product.price.asc())
            elif sort_by == "price_desc":
                query = select(Product).order_by(desc(Product.price))
            else:
                query = select(Product).order_by(desc(Product.hot_score))

            rows = (await db.execute(query.limit(limit))).scalars().all()

        return {
            "sort_by": sort_by,
            "items": [r.to_dict() for r in rows],
        }

    async def keyword_ranking(self, limit: int = 20) -> dict[str, Any]:
        """关键词排行（按采集量）。"""
        async with async_session() as db:
            query = (
                select(Product.keyword, func.count(Product.id).label("cnt"))
                .where(Product.keyword.isnot(None))
                .group_by(Product.keyword)
                .order_by(desc("cnt"))
                .limit(limit)
            )
            rows = (await db.execute(query)).all()

        return {
            "items": [
                {"keyword": r.keyword, "count": r.cnt}
                for r in rows
            ],
        }

    async def category_distribution(self) -> dict[str, Any]:
        """类目分布。"""
        async with async_session() as db:
            query = (
                select(Product.category, func.count(Product.id).label("cnt"))
                .where(Product.category.isnot(None))
                .group_by(Product.category)
                .order_by(desc("cnt"))
            )
            rows = (await db.execute(query)).all()

        return {
            "items": [
                {"category": r.category or "未分类", "count": r.cnt}
                for r in rows
            ],
        }

    async def publish_time_trend(self, keyword: str | None = None) -> dict[str, Any]:
        """发布时间趋势（按天分桶，最近30天）。"""
        from datetime import datetime, timedelta

        async with async_session() as db:
            query = select(Product.publish_time)
            if keyword:
                query = query.where(Product.title.ilike(f"%{keyword}%"))
            rows = (await db.execute(query)).scalars().all()

        dates = [r for r in rows if r is not None]
        if not dates:
            return {"trend": [], "total": 0}

        now = datetime.utcnow()
        # 按天分桶，最近30天
        buckets: dict[str, int] = {}
        for d in dates:
            days_ago = (now - d).days
            if 0 <= days_ago <= 30:
                key = d.strftime("%Y-%m-%d")
                buckets[key] = buckets.get(key, 0) + 1

        trend = sorted(
            [{"date": k, "count": v} for k, v in buckets.items()],
            key=lambda x: x["date"],
        )
        return {"trend": trend, "total": len(dates)}


# 模块级单例
_dashboard: DashboardService | None = None


def get_dashboard() -> DashboardService:
    global _dashboard
    if _dashboard is None:
        _dashboard = DashboardService()
    return _dashboard
