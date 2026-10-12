"""L1 深层采集器：闲鱼商品详情 mtop API（httpx 直请求，带签名）。

Phase 0 探针（用户机实测 2026-10-12）确认的调用与字段：
- POST https://h5api.m.goofish.com/h5/mtop.taobao.idle.pc.detail/1.0/
- params 结构与搜索 API 相同；data = {"itemId": "<id>"}；
  sign = md5(token&t&appKey&data)（token = _m_h5_tk 下划线前半段）
- SUCCESS 响应携带（路径已探针确认，字段位于 data.itemDO）：
    wantCnt    — 想要数（权威源；wantCntUnit='人想要' 与 DOM 口径一致）
    collectCnt — 收藏数
    browseCnt  — 浏览数（曝光代理指标：想要数≠销量、浏览数≠平台曝光）

护栏（见 config.py detail_* 系列）：
- detail_qps：令牌桶限速，默认 0.3（≈3.3s/次）
- detail_risk_break_seconds：触发 RGV587 等风控后的熔断窗，默认 300s
本模块复用 httpx_crawler 的 token/签名/风控关键字机制，不产生搜索流量。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from app.crawlers.base import CrawledProduct, safe_get
from app.crawlers.httpx_crawler import (
    APP_KEY,
    RISK_KEYWORDS,
    TOKEN_FAIL_KEYWORDS,
    generate_sign,
    get_h5_token,
)

logger = logging.getLogger(__name__)

DETAIL_API_NAME = "mtop.taobao.idle.pc.detail"
DETAIL_API_URL = f"https://h5api.m.goofish.com/h5/{DETAIL_API_NAME}/1.0/"

# 兜底默认值（真实配置在 app.config.settings.detail_qps 等）
_FALLBACK_QPS = 0.3
_FALLBACK_BREAK_S = 300.0


def _ret_str(data: dict) -> str:
    ret = data.get("ret") or []
    if isinstance(ret, str):
        return ret
    return " | ".join(str(r) for r in ret)


def _detail_settings() -> tuple[float, float]:
    """读取限速/熔断配置（懒导入避免测试环境依赖 app.config 的顺序问题）。"""
    try:
        from app.config import settings

        return (
            max(0.05, float(getattr(settings, "detail_qps", _FALLBACK_QPS))),
            float(getattr(settings, "detail_risk_break_seconds", _FALLBACK_BREAK_S)),
        )
    except Exception:  # noqa: BLE001
        return _FALLBACK_QPS, _FALLBACK_BREAK_S


class DetailCrawler:
    """深层采集：单商品详情（want/browse/collect 的权威源）。"""

    def __init__(self) -> None:
        self._consecutive_failures = 0
        self._risk_until = 0.0
        self._limiter_last = 0.0
        self._limiter_lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None

    # ---- 生命周期 ----

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _client_or_new(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=20.0,
                follow_redirects=True,
                trust_env=False,
                headers=self._headers(),
                cookies=self._user_cookies(),
            )
        return self._client

    def _user_cookies(self) -> dict[str, str]:
        """登录 cookies（详情 API 实测需要登录态：匿名走 passport 重定向）。"""
        try:
            from app.services.session_manager import get_session

            session = get_session()
            if session.path.exists():
                return session.get_cookies() or {}
        except Exception as e:  # noqa: BLE001
            logger.debug("DetailCrawler cookies 加载失败: %s", e)
        return {}

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://www.goofish.com",
            "Referer": "https://www.goofish.com/",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        }

    # ---- 状态查询 ----

    def risk_paused(self) -> bool:
        """风控熔断中（期间 get_detail 直接返回 None，不发请求）。"""
        return time.monotonic() < self._risk_until

    # ---- 核心：单商品详情 ----

    async def get_detail(self, item_id: str) -> dict[str, Any] | None:
        """取单商品详情计数字段；失败/限流/熔断时返回 None（不抛异常）。"""
        if not item_id or not str(item_id).isdigit():
            return None
        if self.risk_paused():
            logger.debug("DetailCrawler: 熔断中，跳过 %s", item_id)
            return None
        if not await self._limiter_acquire():
            logger.debug("DetailCrawler: 限流丢弃 %s", item_id)
            return None

        token = get_h5_token()
        if not token:
            logger.debug("DetailCrawler: 无 token（需先成功跑一次 L1 搜索引导）")
            return None

        data_val = json.dumps({"itemId": str(item_id)}, separators=(",", ":"))
        t = str(int(time.time() * 1000))
        params = {
            "jsv": "2.7.2",
            "appKey": APP_KEY,
            "t": t,
            "sign": generate_sign(t, token, data_val),
            "v": "1.0",
            "type": "originaljson",
            "accountSite": "xianyu",
            "dataType": "json",
            "timeout": "20000",
            "api": DETAIL_API_NAME,
            "sessionOption": "AutoLoginOnly",
        }
        try:
            client = await self._client_or_new()
            resp = await client.post(
                DETAIL_API_URL, params=params, data={"data": data_val}
            )
        except httpx.HTTPError as e:
            logger.warning("DetailCrawler 网络异常 %s: %s", item_id, e)
            self._consecutive_failures += 1
            return None

        if resp.status_code != 200:
            logger.warning("DetailCrawler HTTP %d for %s", resp.status_code, item_id)
            self._consecutive_failures += 1
            return None
        try:
            payload = resp.json()
        except (json.JSONDecodeError, ValueError):
            logger.warning("DetailCrawler: 响应非 JSON")
            self._consecutive_failures += 1
            return None

        ret = _ret_str(payload)
        if "SUCCESS" in ret:
            self._consecutive_failures = 0
            return self._extract(payload)
        if any(k in ret for k in RISK_KEYWORDS):
            break_s = _detail_settings()[1]
            self._risk_until = time.monotonic() + break_s
            logger.warning("DetailCrawler: 风控触发 [%s] → 熔断 %ds", ret[:80], int(break_s))
            return None
        if any(k in ret for k in TOKEN_FAIL_KEYWORDS):
            logger.warning("DetailCrawler: 令牌失效 [%s]", ret)
            return None
        logger.warning("DetailCrawler: ret not SUCCESS [%s]", ret[:120])
        self._consecutive_failures += 1
        return None

    # ---- 内部 ----

    async def _limiter_acquire(self) -> bool:
        """单调间隔限速：间隔不足则拒绝本次（丢请求优于排队引发突发）。"""
        async with self._limiter_lock:
            qps, _ = _detail_settings()
            interval = 1.0 / qps
            now = time.monotonic()
            if now < self._limiter_last + interval:
                return False
            self._limiter_last = now
            return True

    def _extract(self, payload: dict) -> dict[str, Any] | None:
        """从 SUCCESS 响应提取计数字段（路径探针确认：data.itemDO）。"""
        item_do = safe_get(payload, "data", "itemDO", default=None)
        if not isinstance(item_do, dict) or not item_do:
            return None
        out: dict[str, Any] = {}
        for src, dst in (
            ("wantCnt", "want_count"),
            ("browseCnt", "browse_count"),
            ("collectCnt", "collect_count"),
        ):
            v = item_do.get(src)
            if isinstance(v, str) and v.isdigit():
                v = int(v)
            if isinstance(v, int) and v >= 0:
                out[dst] = v
        return out or None


async def enrich_top_products(
    detail: DetailCrawler,
    products: list[CrawledProduct],
    top_k: int = 20,
    max_seconds: float = 120.0,
) -> float:
    """对已采列表的前 top_k 个商品做详情 enrich（in-place 更新字段）。

    只在事件循环内调用（caller 已在 async 上下文——crawler_service.crawl 本身是 async）。
    返回 enriched 比例（0.0~1.0），供日志与 API 回显。
    """
    targets = [p for p in products if p.xianyu_id][:top_k]
    if not targets:
        return 0.0
    deadline = time.monotonic() + max_seconds
    hits = 0
    for i, p in enumerate(targets):
        if time.monotonic() > deadline:
            logger.info("DetailCrawler enrich: 达到时限（%d/%d 完成）", i, len(targets))
            break
        if detail.risk_paused():
            logger.warning("DetailCrawler enrich: 熔断，提前结束（%d/%d）", i, len(targets))
            break
        fields = await detail.get_detail(p.xianyu_id)
        if fields:
            hits += 1
            # 详情 API 是权威源：直接覆盖（而非仅填空缺）
            p.want_count = fields.get("want_count", p.want_count or 0)
            p.view_count = fields.get("browse_count", p.view_count or 0)
            p.collect_count = fields.get("collect_count", 0)
        await asyncio.sleep(0.05)  # 令牌桶之外的礼貌间隔
    ratio = hits / len(targets)
    logger.info("DetailCrawler enrich: %d/%d 命中（%.0f%%）", hits, len(targets), ratio * 100)
    return ratio
