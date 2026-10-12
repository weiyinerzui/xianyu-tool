"""v0.5.0 schema 验证：新列（collect/c_cat_id/tb_cat_id/rank/detail_enriched）真实可建库。"""

from __future__ import annotations

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import Base


def test_new_columns_create_all():
    """create_all 建库后，products/product_snapshots 必须含全部新列。"""
    import asyncio
    import os
    import tempfile

    async def _run():
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            eng = create_async_engine(f"sqlite+aiosqlite:///{path}")
            async with eng.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with eng.connect() as conn:
                def _check(c) -> None:
                    insp = sa_inspect(c)
                    prods = {x["name"] for x in insp.get_columns("products")}
                    snaps = {x["name"] for x in insp.get_columns("product_snapshots")}
                    need = {
                        "collect_count", "c_cat_id", "tb_cat_id",
                        "rank_position", "detail_enriched",
                    }
                    assert need <= prods, f"products 缺列: {need - prods}"
                    assert "collect_count" in snaps, "snapshots 缺 collect_count"
                await conn.run_sync(_check)
            await eng.dispose()
        finally:
            os.unlink(path)

    asyncio.run(_run())
