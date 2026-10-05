"""商品快照模型（P1-1）。

「想要数增速」本质是时间序列指标：需要同一商品在两个时间点的想要数才能算出增速。
原实现没有历史表，scheduler 里 previous_want 被硬编码为 None，
导致权重最高的 want_velocity(0.35) 永久为 0。

本表记录每次采集时观察到的商品状态，是增速、降价检测、竞品价格追踪的数据基础。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProductSnapshot(Base):
    """商品状态快照（时序）。"""

    __tablename__ = "product_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    xianyu_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    want_count: Mapped[int] = mapped_column(Integer, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float] = mapped_column(Float, default=0)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True, default=datetime.utcnow)

    __table_args__ = (
        # 同一商品的快照按时间排序：查「上一条快照」时走索引
        Index("ix_snapshot_xianyu_time", "xianyu_id", "captured_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "xianyu_id": self.xianyu_id,
            "want_count": self.want_count,
            "view_count": self.view_count,
            "price": self.price,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
        }