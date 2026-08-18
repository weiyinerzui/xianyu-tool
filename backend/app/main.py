"""FastAPI 主入口。

启动：uvicorn app.main:app --port 8000 --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库。"""
    from app.database import init_db

    await init_db()
    yield


app = FastAPI(
    title="闲鱼店铺运营工具 API",
    description="选品 · 违禁词检测 · 曝光诊断 · 标题优化 · 采集 · 风控",
    version="0.2.0",
    lifespan=lifespan,
)

# 允许前端跨域（开发期）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "闲鱼店铺运营工具 API",
        "version": "0.2.0",
        "docs": "/docs",
        "endpoints": "/api/v1",
    }
