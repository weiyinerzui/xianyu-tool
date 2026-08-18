"""商品数据模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Product(Base):
    """闲鱼商品（采集来的竞品数据）。"""
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    xianyu_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    price: Mapped[float] = mapped_column(Float, default=0)
    original_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    want_count: Mapped[int] = mapped_column(Integer, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    seller_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    seller_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    area: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    publish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hot_score: Mapped[float] = mapped_column(Float, default=0)
    want_velocity: Mapped[float] = mapped_column(Float, default=0)
    price_advantage: Mapped[float] = mapped_column(Float, default=0)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0)
    freshness: Mapped[float] = mapped_column(Float, default=0)
    competition: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(20), default="search", index=True)
    keyword: Mapped[str | None] = mapped_column(String(200), index=True, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "xianyu_id": self.xianyu_id,
            "title": self.title,
            "price": self.price,
            "original_price": self.original_price,
            "want_count": self.want_count,
            "view_count": self.view_count,
            "seller_name": self.seller_name,
            "area": self.area,
            "category": self.category,
            "tags": self.tags,
            "image_url": self.image_url,
            "link": self.link,
            "publish_time": self.publish_time.isoformat() if self.publish_time else None,
            "hot_score": self.hot_score,
            "want_velocity": self.want_velocity,
            "price_advantage": self.price_advantage,
            "engagement_rate": self.engagement_rate,
            "freshness": self.freshness,
            "competition": self.competition,
            "source": self.source,
            "keyword": self.keyword,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }
