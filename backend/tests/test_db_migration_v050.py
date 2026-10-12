"""数据库轻量迁移测试：v0.4 老库 → init_db → v0.5.0 新列补齐。

背景（2026-10-12 用户机真实回归发现）：
create_all 只建缺失的表，不给已有表加新列。用户库 product_snapshots
是 v0.4 结构 → 采集落快照时 SELECT 直接报 no such column。
init_db 现在负责 ALTER ADD COLUMN 补列 + c_cat_id 索引。
"""

from __future__ import annotations

import asyncio
import os
import tempfile

from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

import app.database as dbmod
from app.database import init_db


_OLD_TABLES = {
    "products": """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            xianyu_id VARCHAR(100) NOT NULL UNIQUE,
            title VARCHAR(500) NOT NULL,
            price FLOAT DEFAULT 0,
            original_price FLOAT,
            want_count INTEGER DEFAULT 0,
            view_count INTEGER DEFAULT 0,
            seller_name VARCHAR(100),
            seller_level VARCHAR(50),
            area VARCHAR(100),
            category VARCHAR(100),
            tags JSON,
            image_url TEXT,
            link TEXT,
            publish_time DATETIME,
            hot_score FLOAT DEFAULT 0,
            want_velocity FLOAT DEFAULT 0,
            price_advantage FLOAT DEFAULT 0,
            engagement_rate FLOAT DEFAULT 0,
            freshness FLOAT DEFAULT 0,
            competition FLOAT DEFAULT 0,
            source VARCHAR(20) DEFAULT 'search',
            keyword VARCHAR(200),
            fetched_at DATETIME,
            created_at DATETIME
        )
    """,
    "product_snapshots": """
        CREATE TABLE product_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            xianyu_id VARCHAR(100) NOT NULL,
            want_count INTEGER DEFAULT 0,
            view_count INTEGER DEFAULT 0,
            price FLOAT DEFAULT 0,
            captured_at DATETIME NOT NULL
        )
    """,
}


def test_old_schema_upgraded_in_place():
    """老结构库（v0.4 列集）→ init_db → 新列+索引齐备，老数据保留。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        async def _run():
            # 1) 建一个只有 v0.4 列的库，塞一条老数据
            eng = create_async_engine(f"sqlite+aiosqlite:///{path}")
            async with eng.begin() as conn:
                for ddl in _OLD_TABLES.values():
                    await conn.execute(text(ddl))
                await conn.execute(
                    text(
                        "INSERT INTO products (xianyu_id, title, price, want_count) "
                        "VALUES ('1073794772566', 'Python教材', 16.8, 303)"
                    )
                )
            await eng.dispose()

            # 2) init_db 使用的 engine 指向该库；跑迁移；恢复原 engine
            saved = dbmod.engine
            dbmod.engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
            try:
                await init_db()
            finally:
                await dbmod.engine.dispose()
                dbmod.engine = saved

            # 3) 断言：新列全在，老数据未丢，索引存在
            chk = create_async_engine(f"sqlite+aiosqlite:///{path}")
            async with chk.connect() as conn:
                def _check(c):
                    insp = sa_inspect(c)
                    prods = {x["name"] for x in insp.get_columns("products")}
                    snaps = {x["name"] for x in insp.get_columns("product_snapshots")}
                    assert {"collect_count", "c_cat_id", "tb_cat_id", "rank_position", "detail_enriched"} <= prods
                    assert "collect_count" in snaps
                    idx = {i["name"] for i in insp.get_indexes("products")}
                    assert "ix_products_c_cat_id" in idx, f"缺 c_cat_id 索引: {idx}"
                    row = c.execute(text(
                        "SELECT xianyu_id, want_count FROM products LIMIT 1"
                    )).fetchone()
                    assert row and row[0] == "1073794772566" and row[1] == 303, f"老数据丢失: {row}"
                await conn.run_sync(_check)
            await chk.dispose()

        asyncio.run(_run())
    finally:
        os.unlink(path)
