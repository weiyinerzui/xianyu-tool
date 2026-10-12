"""数据库配置（SQLAlchemy 异步 + SQLite）。"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """建表 + 轻量列迁移。

    create_all 只建缺失的表，不给已有表加新列——SQLite 升级路径
    （v0.4→v0.5）需要给 products/product_snapshots 补 v0.5.0 新列。
    老库自动补列（带默认值，旧行读出为默认值）；新库 create_all 直接建成。
    """
    # 导入所有模型以注册 metadata（snapshot 提供增速计算所需的时序数据）
    from app.models import crawl_task, product, snapshot  # noqa: F401

    from sqlalchemy import inspect as sa_inspect, text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def _add_missing_columns(sync_conn) -> None:
            insp = sa_inspect(sync_conn)
            # {表: {列名: 列 DDL 类型}}——与 models 定义保持一致（单一事实源：模型）
            from app.database import _MIGRATION_V050_COLUMNS

            for table, cols in _MIGRATION_V050_COLUMNS.items():
                if table not in insp.get_table_names():
                    continue
                existing = {c["name"] for c in insp.get_columns(table)}
                for col_name, col_type in cols.items():
                    if col_name in existing:
                        continue
                    conn_sql = text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                    sync_conn.execute(conn_sql)
                    logger.info("数据库迁移: %s.%s += %s", table, col_name, col_type)
            # c_cat_id 是聚合主键，老库需要补索引（SQLite ALTER ADD COLUMN 不带索引）
            if "products" in insp.get_table_names():
                sync_conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_products_c_cat_id ON products (c_cat_id)")
                )

        await conn.run_sync(_add_missing_columns)


# v0.5.0 新增列（SQLite ALTER ADD COLUMN 语法；默认值由模型 default 兜底）。
# 维护规则：模型加列 ⟹ 此处登记 ⟹ 老库自动补。index 通过 CREATE INDEX 单独处理：
# SQLite 的 ALTER ADD COLUMN 不支持索引，需建列后手动 CREATE INDEX IF NOT EXISTS。
_MIGRATION_V050_COLUMNS: dict[str, dict[str, str]] = {
    "products": {
        "collect_count": "INTEGER DEFAULT 0",
        "c_cat_id": 'VARCHAR(50) DEFAULT ""',
        "tb_cat_id": 'VARCHAR(50) DEFAULT ""',
        "rank_position": "INTEGER DEFAULT 0",
        "detail_enriched": "BOOLEAN DEFAULT 0",
    },
    "product_snapshots": {
        "collect_count": "INTEGER DEFAULT 0",
    },
}
