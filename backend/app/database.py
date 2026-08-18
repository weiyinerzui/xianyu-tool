"""数据库配置（SQLAlchemy 异步 + SQLite）。"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """创建所有表。"""
    from app.models import product, crawl_task  # noqa: F401  确保模型被导入

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
