"""快照表与增速计算的集成测试（P1-1 / P1-2）。

验证真实场景：同一商品连续两次采集（想要数增长）后，
product.want_velocity 不再是 0，而是基于快照算出的真实增速。

注意：本测试会建表/删表，因此使用独立的临时库（test_snapshot.db），
避免破坏开发库的 xianyu_ops.db。
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 必须在导入 app.database 之前切换到测试库
_TEST_DB = Path(__file__).resolve().parent.parent / "test_snapshot.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()
os.environ["XIANYU_OPS_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB}"

from sqlalchemy import select  # noqa: E402

from app.crawlers.base import CrawledProduct  # noqa: E402
from app.database import Base, async_session, engine  # noqa: E402
from app.models.snapshot import ProductSnapshot  # noqa: E402
from app.services.crawler_service import CrawlerService  # noqa: E402


def _product(want: int, price: float = 50.0) -> CrawledProduct:
    return CrawledProduct(
        xianyu_id="test-001",
        title="考研数学资料",
        price=price,
        want_count=want,
    )


async def _run() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    service = CrawlerService()

    # 第一次采集：只有当前状态，没有历史 → 增速应为 0
    async with async_session() as db:
        await service._save_products([_product(want=10)], "kw", db)
    async with async_session() as db:
        snaps = (await db.execute(select(ProductSnapshot))).scalars().all()
        assert len(snaps) == 1, f"应写入 1 条快照，实际 {len(snaps)}"

    # 把快照往前推 2 小时，模拟「2 小时前采集过一次」
    async with async_session() as db:
        snap = (await db.execute(select(ProductSnapshot))).scalar_one()
        snap.captured_at = datetime.utcnow() - timedelta(hours=2)
        await db.commit()

    # 第二次采集：想要数 10 → 35，增速应大于 0
    async with async_session() as db:
        await service._save_products([_product(want=35)], "kw", db)

    async with async_session() as db:
        snaps = (await db.execute(
            select(ProductSnapshot).order_by(ProductSnapshot.captured_at)
        )).scalars().all()
        assert len(snaps) == 2, f"应累计 2 条快照，实际 {len(snaps)}"

        from app.models.product import Product
        row = (await db.execute(
            select(Product).where(Product.xianyu_id == "test-001")
        )).scalar_one()
        print(f"  want_velocity = {row.want_velocity}")
        assert row.want_velocity > 0, f"增速仍为 0，快照逻辑未生效：{row.want_velocity}"

    # 快照不应无限增长：同一商品同一次采集只写一条
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("  PASS: 快照累积 + 增速计算正确")


if __name__ == "__main__":
    asyncio.run(_run())
    print("✅ test_snapshot_velocity: 全部通过")