"""竞品监控服务：监控头部卖家动态。

功能：
- 卖家排行（按在售商品数/想要数总和）
- 卖家商品列表
- 价格变动检测（对比历史采集数据）
- 新品检测（最近24h新发布的商品）
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select

from app.database import async_session
from app.models.product import Product


class CompetitorMonitor:
    """竞品监控。"""

    async def top_sellers(self, limit: int = 20) -> dict[str, Any]:
        """头部卖家排行（按在售商品数 + 想要数总和）。"""
        async with async_session() as db:
            query = (
                select(
                    Product.seller_name,
                    func.count(Product.id).label("listing_count"),
                    func.sum(Product.want_count).label("total_wants"),
                    func.avg(Product.price).label("avg_price"),
                )
                .where(Product.seller_name.isnot(None), Product.seller_name != "")
                .group_by(Product.seller_name)
                .order_by(desc("total_wants"))
                .limit(limit)
            )
            rows = (await db.execute(query)).all()

        return {
            "items": [
                {
                    "seller_name": r.seller_name,
                    "listing_count": r.listing_count,
                    "total_wants": int(r.total_wants or 0),
                    "avg_price": round(float(r.avg_price or 0), 2),
                }
                for r in rows
            ],
        }

    async def seller_products(self, seller_name: str, limit: int = 50) -> dict[str, Any]:
        """指定卖家的商品列表。"""
        async with async_session() as db:
            query = (
                select(Product)
                .where(Product.seller_name == seller_name)
                .order_by(desc(Product.want_count))
                .limit(limit)
            )
            rows = (await db.execute(query)).scalars().all()

        return {
            "seller_name": seller_name,
            "total": len(rows),
            "items": [r.to_dict() for r in rows],
        }

    async def new_listings(self, hours: int = 24, limit: int = 50) -> dict[str, Any]:
        """最近 N 小时的新品。"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        async with async_session() as db:
            query = (
                select(Product)
                .where(Product.publish_time >= cutoff)
                .order_by(desc(Product.publish_time))
                .limit(limit)
            )
            rows = (await db.execute(query)).scalars().all()

        return {
            "hours": hours,
            "total": len(rows),
            "items": [r.to_dict() for r in rows],
        }

    async def price_changes(self, keyword: str | None = None) -> dict[str, Any]:
        """价格变动检测（对比同一商品最近两次采集的价格）。

        由于当前模型每次采集更新 price 字段，这里通过 fetched_at 时间差
        检测有多次采集记录的商品（简化版：列出价格低于类目均价的商品）。
        """
        async with async_session() as db:
            query = select(Product)
            if keyword:
                query = query.where(Product.title.ilike(f"%{keyword}%"))
            rows = (await db.execute(query)).scalars().all()

        from app.services.scorer import calc_category_avg_price

        prices = [r.price for r in rows if r.price > 0]
        avg = calc_category_avg_price(prices)

        # 价格低于均价 70% 的商品（可能是降价了）
        below_market = [
            {
                "xianyu_id": r.xianyu_id,
                "title": r.title,
                "price": r.price,
                "avg_price": round(avg, 2),
                "deviation": round((r.price - avg) / avg * 100, 1) if avg else 0,
                "seller_name": r.seller_name,
            }
            for r in rows
            if r.price > 0 and avg > 0 and r.price < avg * 0.7
        ]
        below_market.sort(key=lambda x: x["deviation"])

        return {
            "avg_price": round(avg, 2),
            "below_market_count": len(below_market),
            "items": below_market[:30],
        }


# 模块级单例
_monitor: CompetitorMonitor | None = None


def get_monitor() -> CompetitorMonitor:
    global _monitor
    if _monitor is None:
        _monitor = CompetitorMonitor()
    return _monitor
