"""API 路由：违禁词检测、曝光诊断、标题优化。

所有路由前缀 /api/v1。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.banned_checker import get_checker
from app.services.diagnosis_engine import get_engine
from app.services.title_advisor import get_advisor

router = APIRouter(prefix="/api/v1", tags=["xianyu-ops"])


# ============================================================
# 违禁词检测
# ============================================================

class CheckRequest(BaseModel):
    text: str = Field(..., description="待检测文本（标题/描述/消息）")


class CheckBatchRequest(BaseModel):
    texts: list[str] = Field(..., description="待检测文本列表")


@router.post("/banned/check", summary="违禁词检测")
def banned_check(req: CheckRequest) -> dict[str, Any]:
    """检测单条文本是否含违禁词，返回分级结果 + 替换建议。"""
    result = get_checker().check(req.text)
    return result.to_dict()


@router.post("/banned/check-batch", summary="违禁词批量检测")
def banned_check_batch(req: CheckBatchRequest) -> dict[str, Any]:
    """批量检测多条文本。"""
    results = get_checker().check_batch(req.texts)
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "blocked": sum(1 for r in results if not r.passed),
        "results": [r.to_dict() for r in results],
    }


# ============================================================
# 曝光诊断
# ============================================================

class DiagnoseRequest(BaseModel):
    item_id: str = ""
    title: str = ""
    price: float | None = None
    market_avg_price: float | None = None
    category: str = ""
    recommended_category: str = ""
    category_mismatch: bool | None = None
    image_count: int | None = None
    first_image_ratio: str = "1:1"
    has_watermark: bool | None = None
    desc_length: int | None = None
    publish_hours: float | None = None
    exposure_trend: str = ""
    price_changed: bool | None = None
    title_changed: bool | None = None
    price_title_change_within_24h: bool | None = None
    edit_count_within_1h: int | None = None
    account_health_score: float | None = None
    has_violation_record: bool | None = None
    account_age_days: int | None = None
    daily_publish_count: int | None = None
    is_verified: bool | None = None
    similar_listing_count: int | None = None
    has_core_keyword: bool | None = None
    keyword_front_loaded: bool | None = None


@router.post("/diagnosis/diagnose", summary="曝光诊断")
def diagnose(req: DiagnoseRequest) -> dict[str, Any]:
    """对商品元数据进行曝光归因诊断，返回嫌疑归因 + 修复建议。"""
    item = req.model_dump(exclude_none=True)
    report = get_engine().diagnose(item)
    return report.to_dict()


# ============================================================
# 标题优化
# ============================================================

class TitleScoreRequest(BaseModel):
    title: str = Field(..., description="待评分标题")
    core_keyword: str = Field("", description="核心词（用于判断前置和覆盖）")


class TitleGenerateRequest(BaseModel):
    core_keyword: str = Field(..., description="核心词（必填）")
    attribute: str = Field("", description="属性/规格")
    brand: str = Field("", description="品牌")
    scene: str = Field("", description="场景")
    emotion: str = Field("", description="情感/成色")


@router.post("/title/score", summary="标题评分")
def title_score(req: TitleScoreRequest) -> dict[str, Any]:
    """对标题按5段式公式评分，返回得分 + 问题 + 优化建议。"""
    result = get_advisor().score(req.title, req.core_keyword)
    return result.to_dict()


@router.post("/title/generate", summary="标题生成")
def title_generate(req: TitleGenerateRequest) -> dict[str, Any]:
    """根据5段式输入生成候选标题（已过滤违禁词）。"""
    candidates = get_advisor().generate(
        core_keyword=req.core_keyword,
        attribute=req.attribute,
        brand=req.brand,
        scene=req.scene,
        emotion=req.emotion,
    )
    return {
        "candidates": candidates,
        "count": len(candidates),
    }


# ============================================================
# 采集与选品
# ============================================================

class CrawlRequest(BaseModel):
    keyword: str = Field(..., description="搜索关键词")
    category: str | None = Field(None, description="类目（可选）")


@router.post("/crawl/search", summary="采集搜索（触发爬取+存储）")
async def crawl_search(req: CrawlRequest) -> dict[str, Any]:
    """触发采集：L1(httpx)→L2(playwright) 两级降级，结果存入数据库。"""
    from app.database import async_session
    from app.services.crawler_service import get_crawler_service

    service = get_crawler_service()
    async with async_session() as db:
        products, source = await service.crawl(req.keyword, req.category, db)
    return {
        "keyword": req.keyword,
        "source": source,
        "total": len(products),
        "products": [p.to_dict() for p in products[:50]],
    }


@router.get("/products/search", summary="选品查询（从库中查已采集商品）")
async def products_search(
    keyword: str | None = None,
    category: str | None = None,
    sort: str = "hotness",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询已采集的商品，按热度/价格/想要数排序。"""
    from datetime import datetime

    from sqlalchemy import desc, func, select

    from app.database import async_session
    from app.models.product import Product
    from app.services.scorer import calc_days_ago, calc_hotness

    async with async_session() as db:
        query = select(Product)
        if keyword:
            query = query.where(Product.title.ilike(f"%{keyword}%"))
        if category:
            query = query.where(Product.category == category)

        count_q = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        if sort == "price_asc":
            query = query.order_by(Product.price.asc())
        elif sort == "price_desc":
            query = query.order_by(Product.price.desc())
        elif sort == "want_count":
            query = query.order_by(desc(Product.want_count))
        elif sort == "newest":
            query = query.order_by(desc(Product.publish_time))
        else:  # hotness
            query = query.order_by(desc(Product.want_count), desc(Product.hot_score))

        query = query.offset((page - 1) * page_size).limit(page_size)
        rows = (await db.execute(query)).scalars().all()

        items = []
        for p in rows:
            d = p.to_dict()
            d["days_ago"] = calc_days_ago(p.publish_time)
            d["hotness"] = round(calc_hotness(p.want_count, p.publish_time), 2)
            items.append(d)

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/products/stats", summary="选品统计（价格带+竞争度）")
async def products_stats(keyword: str | None = None) -> dict[str, Any]:
    """统计已采集商品的价格分布、竞争度等。"""
    from sqlalchemy import func, select

    from app.database import async_session
    from app.models.product import Product
    from app.services.scorer import calc_category_avg_price, calc_competition

    async with async_session() as db:
        query = select(Product)
        if keyword:
            query = query.where(Product.title.ilike(f"%{keyword}%"))
        rows = (await db.execute(query)).scalars().all()

    if not rows:
        return {"total": 0}

    prices = [r.price for r in rows if r.price > 0]
    want_counts = [r.want_count for r in rows]
    avg_price = calc_category_avg_price(prices)

    # 价格带分布
    sorted_prices = sorted(prices)
    n = len(sorted_prices)
    bands = {
        "min": sorted_prices[0] if prices else 0,
        "p25": sorted_prices[n // 4] if n > 4 else (sorted_prices[0] if prices else 0),
        "median": sorted_prices[n // 2] if prices else 0,
        "p75": sorted_prices[3 * n // 4] if n > 4 else (sorted_prices[-1] if prices else 0),
        "max": sorted_prices[-1] if prices else 0,
        "avg": round(avg_price, 2),
    }

    return {
        "total": len(rows),
        "price_bands": bands,
        "avg_want_count": round(sum(want_counts) / len(want_counts), 1) if want_counts else 0,
        "max_want_count": max(want_counts) if want_counts else 0,
        "competition_score": round(calc_competition(len(rows)), 2),
    }


# ============================================================
# 风控护栏
# ============================================================

@router.get("/guard/status", summary="风控状态")
def guard_status() -> dict[str, Any]:
    """查询限流器 + 熔断器状态。"""
    from app.services.guard import get_guard, get_limiter

    limiter = get_limiter()
    guard = get_guard()

    return {
        "limiter": {
            ns: b.to_dict() for ns, b in limiter._buckets.items()
        },
        "circuit": {
            "tripped": guard.is_tripped("default"),
            "remaining_seconds": round(guard.remaining("default"), 1),
        },
    }


@router.post("/guard/reset", summary="重置熔断器")
def guard_reset() -> dict[str, str]:
    """手动重置熔断器（只解本地熔断，不解服务端风控）。"""
    from app.services.guard import get_guard

    get_guard().reset("default")
    return {"status": "reset", "note": "仅重置本地熔断状态，服务端风控需人工处理"}


# ============================================================
# 登录态管理
# ============================================================

@router.get("/session/status", summary="登录态状态")
def session_status() -> dict[str, Any]:
    """查询当前登录态（脱敏）。"""
    from app.services.session_manager import SessionError, get_session

    try:
        return get_session().status()
    except SessionError as e:
        return {"valid": False, "reason": str(e)}


class SessionImportRequest(BaseModel):
    cookies: dict[str, str] = Field(..., description="cookie dict")


@router.post("/session/import", summary="导入登录态")
def session_import(req: SessionImportRequest) -> dict[str, Any]:
    """导入 cookie（从浏览器 DevTools 导出后粘贴）。"""
    from app.services.session_manager import REQUIRED_COOKIE_KEYS, get_session

    sm = get_session()
    sm.save(req.cookies)
    valid = all(k in req.cookies for k in REQUIRED_COOKIE_KEYS)
    return {"saved": True, "valid": valid, "status": sm.status()}


# ============================================================
# 定时采集
# ============================================================

@router.get("/scheduler/status", summary="调度器状态")
def scheduler_status() -> dict[str, Any]:
    """查询定时采集调度器状态。"""
    from app.services.scheduler import get_scheduler
    return get_scheduler().status()


@router.post("/scheduler/run", summary="手动触发一次采集")
async def scheduler_run() -> dict[str, Any]:
    """手动触发一次采集任务。"""
    from app.services.scheduler import get_scheduler
    return await get_scheduler().run_once()


class SchedulerKeywordsRequest(BaseModel):
    keywords: list[str] = Field(..., description="采集关键词列表")


@router.post("/scheduler/keywords", summary="设置采集关键词")
def scheduler_set_keywords(req: SchedulerKeywordsRequest) -> dict[str, Any]:
    """设置定时采集的关键词列表。"""
    from app.services.scheduler import get_scheduler
    get_scheduler().set_keywords(req.keywords)
    return {"status": "ok", "keywords": req.keywords}


# ============================================================
# 数据看板
# ============================================================

@router.get("/dashboard/overview", summary="总览统计")
async def dashboard_overview(keyword: str | None = None) -> dict[str, Any]:
    from app.services.dashboard import get_dashboard
    return await get_dashboard().overview(keyword)


@router.get("/dashboard/price-distribution", summary="价格分布")
async def dashboard_price_distribution(keyword: str | None = None, bins: int = 10) -> dict[str, Any]:
    from app.services.dashboard import get_dashboard
    return await get_dashboard().price_distribution(keyword, bins)


@router.get("/dashboard/top-products", summary="热门商品排行")
async def dashboard_top_products(sort_by: str = "hot_score", limit: int = 20) -> dict[str, Any]:
    from app.services.dashboard import get_dashboard
    return await get_dashboard().top_products(sort_by, limit)


@router.get("/dashboard/keyword-ranking", summary="关键词排行")
async def dashboard_keyword_ranking(limit: int = 20) -> dict[str, Any]:
    from app.services.dashboard import get_dashboard
    return await get_dashboard().keyword_ranking(limit)


@router.get("/dashboard/category-distribution", summary="类目分布")
async def dashboard_category_distribution() -> dict[str, Any]:
    from app.services.dashboard import get_dashboard
    return await get_dashboard().category_distribution()


@router.get("/dashboard/publish-trend", summary="发布时间趋势")
async def dashboard_publish_trend(keyword: str | None = None) -> dict[str, Any]:
    from app.services.dashboard import get_dashboard
    return await get_dashboard().publish_time_trend(keyword)


# ============================================================
# 竞品监控
# ============================================================

@router.get("/competitors/top-sellers", summary="头部卖家排行")
async def competitors_top_sellers(limit: int = 20) -> dict[str, Any]:
    from app.services.competitor_monitor import get_monitor
    return await get_monitor().top_sellers(limit)


@router.get("/competitors/seller/{seller_name}", summary="卖家商品列表")
async def competitors_seller_products(seller_name: str, limit: int = 50) -> dict[str, Any]:
    from app.services.competitor_monitor import get_monitor
    return await get_monitor().seller_products(seller_name, limit)


@router.get("/competitors/new-listings", summary="最近新品")
async def competitors_new_listings(hours: int = 24, limit: int = 50) -> dict[str, Any]:
    from app.services.competitor_monitor import get_monitor
    return await get_monitor().new_listings(hours, limit)


@router.get("/competitors/price-changes", summary="价格变动检测")
async def competitors_price_changes(keyword: str | None = None) -> dict[str, Any]:
    from app.services.competitor_monitor import get_monitor
    return await get_monitor().price_changes(keyword)


# ============================================================
# LLM 智能优化
# ============================================================

class LLMTitleRequest(BaseModel):
    title: str = Field(..., description="原标题")
    core_keyword: str = Field("", description="核心词")
    category: str = Field("", description="类目")


class LLMDescriptionRequest(BaseModel):
    title: str = Field(..., description="商品标题")
    category: str = Field("", description="类目")
    key_features: str = Field("", description="关键特征")


@router.post("/llm/optimize-title", summary="LLM标题优化")
async def llm_optimize_title(req: LLMTitleRequest) -> dict[str, Any]:
    """LLM 优化标题（未配置 API key 时降级为规则引擎）。"""
    from app.services.llm_advisor import get_llm
    return await get_llm().optimize_title(req.title, req.core_keyword, req.category)


@router.post("/llm/generate-description", summary="LLM描述生成")
async def llm_generate_description(req: LLMDescriptionRequest) -> dict[str, Any]:
    """LLM 生成商品描述（未配置 API key 时降级为规则引擎）。"""
    from app.services.llm_advisor import get_llm
    return await get_llm().generate_description(req.title, req.category, req.key_features)


@router.get("/llm/status", summary="LLM状态")
def llm_status() -> dict[str, Any]:
    """查询 LLM 是否可用。"""
    from app.services.llm_advisor import get_llm
    llm = get_llm()
    return {"enabled": llm.enabled, "model": llm._model if llm.enabled else "none"}


# ============================================================
# 健康检查
# ============================================================

@router.get("/health", summary="健康检查")
def health() -> dict[str, str]:
    return {"status": "ok"}
