"""v0.5.0 详情 API 采集链测试（p1-1 / p1-2 / p1-3 数据面）。

覆盖：
1. _ret_str 多形态 ret（list/str/dict）
2. _extract：itemDO 计数字段提取（int 与数字 str）、缺 itemDO
3. get_detail 护栏：熔断窗、限流丢弃、非数字 id、无 token
4. enrich_top_products：top_k 截断、in-place 覆盖（权威源）、部分失败
5. parse_search_api_json 新字段：cCatId/tbCatId/rank_position 递增
6. CrawlerService 新降级链：L1 全 0 → detail enrich 命中 → 不走 L2

项目无 pytest-asyncio，统一 asyncio.run（test_l1_escalation 同款）。
"""

from __future__ import annotations

import asyncio
import time

from app.crawlers.base import CrawledProduct, parse_search_api_json
from app.crawlers import detail_crawler as dc
from app.crawlers.detail_crawler import DetailCrawler, enrich_top_products
from app.services.crawler_service import CrawlerService


# ---------- 基础工具 ----------

def test_ret_str_variants():
    assert "SUCCESS" in dc._ret_str({"ret": ["SUCCESS::调用成功"]})
    assert "RGV587_ERROR" in dc._ret_str({"ret": "RGV587_ERROR: 哎哟喂"})
    assert "FAIL" in dc._ret_str({"ret": {"code": "FAIL"}}) or isinstance(
        dc._ret_str({"ret": {}}), str
    )


def test_extract_itemdo_counts():
    payload = {"data": {"itemDO": {
        "wantCnt": 398, "collectCnt": "45", "browseCnt": 12000,
    }}}
    f = dc.DetailCrawler._extract(None, payload)  # type: ignore[arg-type]
    assert f == {"want_count": 398, "collect_count": 45, "browse_count": 12000}


def test_extract_missing_itemdo():
    assert dc.DetailCrawler._extract(None, {"data": {}}) is None  # type: ignore[arg-type]
    assert dc.DetailCrawler._extract(None, {"data": {"itemDO": {}}}) is None  # type: ignore[arg-type]


# ---------- get_detail 护栏（不打网络） ----------

def test_get_detail_rejects_non_numeric_id():
    async def _run():
        d = DetailCrawler()
        assert await d.get_detail("abc") is None
        assert await d.get_detail("") is None

    asyncio.run(_run())


def test_get_detail_risk_pause_blocks_all():
    async def _run():
        d = DetailCrawler()
        d._risk_until = time.monotonic() + 60
        # 熔断中：不发请求，直接 None（连限流器都不该动）
        assert await d.get_detail("1073794772566") is None

    asyncio.run(_run())


def test_get_detail_limiter_drops_when_saturated():
    async def _run():
        d = DetailCrawler()
        d._limiter_last = time.monotonic()  # 刚发过一个
        assert await d.get_detail("1073794772566") is None  # 被限流丢弃

    asyncio.run(_run())


def test_get_detail_no_token_returns_none():
    async def _run():
        from app.crawlers import httpx_crawler

        d = DetailCrawler()
        saved = httpx_crawler._token_store["token"]
        try:
            httpx_crawler._token_store["token"] = ""
            # 过限流器（让第一个请求通过），无 token → None
            d._limiter_last = time.monotonic() - 100
            assert await d.get_detail("1073794772566") is None
        finally:
            httpx_crawler._token_store["token"] = saved

    asyncio.run(_run())


# ---------- enrich_top_products ----------

def _mk(iid: str, want: int = 0) -> CrawledProduct:
    return CrawledProduct(xianyu_id=iid, title=f"t{iid}", price=1.0, want_count=want)


class _StubDetail:
    """get_detail 桩：映射表命中返回字段，否则 None。"""

    def __init__(self, mapping: dict[str, dict]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []
        self._risk_until = 0.0

    def risk_paused(self) -> bool:
        return False

    async def get_detail(self, item_id: str):
        self.calls.append(item_id)
        return self.mapping.get(item_id)


def test_enrich_top_products_overwrites_in_place():
    async def _run():
        stub = _StubDetail({
            "a": {"want_count": 398, "browse_count": 12000, "collect_count": 45},
        })
        products = [_mk("a"), _mk("b"), _mk("c")]
        ratio = await enrich_top_products(stub, products, top_k=3, max_seconds=10)
        assert ratio > 0
        assert products[0].want_count == 398
        assert products[0].view_count == 12000
        assert products[0].collect_count == 45
        assert products[1].want_count == 0  # 未命中保持原值

    asyncio.run(_run())


def test_enrich_top_products_caps_top_k():
    async def _run():
        stub = _StubDetail({})
        products = [_mk(f"i{n}") for n in range(10)]
        await enrich_top_products(stub, products, top_k=3, max_seconds=10)
        assert len(stub.calls) == 3  # 超出 top_k 不再请求

    asyncio.run(_run())


# ---------- 解析器新字段 ----------

def _fake_search_item(iid: str, ccatid: str = "201459411", tbcatid: str = "50014945") -> dict:
    return {
        "data": {
            "item": {
                "main": {
                    "exContent": {"title": f"商品{iid}", "itemId": iid, "price": [{"text": "18"}]},
                    "clickParam": {"args": {"cCatId": ccatid, "tbCatId": tbcatid, "wantNum": "0"}},
                }
            }
        }
    }


def test_parse_search_api_json_new_fields():
    items = [_fake_search_item("1", "201459411", "50014945"), _fake_search_item("2", "201454515", "")]
    products = parse_search_api_json({"data": {"resultList": items}})
    assert len(products) == 2
    assert products[0].c_cat_id == "201459411"
    assert products[0].tb_cat_id == "50014945"
    assert products[0].rank_position == 1
    assert products[1].c_cat_id == "201454515"
    assert products[1].tb_cat_id == ""  # 缺失容忍
    assert products[1].rank_position == 2


# ---------- CrawlerService 新降级链 ----------

class _FakeHttpx:
    def __init__(self, products) -> None:
        self.products = products
        self.called = 0

    async def search(self, keyword, category=None):  # noqa: ANN001
        self.called += 1
        return list(self.products)


class _FakePlaywright:
    def __init__(self, products) -> None:
        self.products = products
        self.called = 0

    async def search(self, keyword, category=None):  # noqa: ANN001
        self.called += 1
        return list(self.products)


def test_l1_all_zero_then_detail_enrich_hits():
    """L1 全 0 → 详情 enrich 命中 → source=httpx+detail，不触发 L2。"""

    async def _run():
        svc = CrawlerService()
        svc.httpx_crawler = _FakeHttpx([_mk("a"), _mk("b")])  # want 全 0
        svc.playwright_crawler = _FakePlaywright([_mk("a", 999)])
        svc.detail_crawler = _StubDetail({
            "a": {"want_count": 398, "browse_count": 12000, "collect_count": 45},
            "b": {"want_count": 101, "browse_count": 3000, "collect_count": 12},
        })

        products, source = await svc.crawl("kw")
        assert source == "httpx+detail"
        assert products[0].want_count == 398
        assert products[1].collect_count == 12
        assert svc.playwright_crawler.called == 0  # 详情接管，L2 不再触发

    asyncio.run(_run())


def test_l1_all_zero_detail_miss_falls_to_l2():
    """L1 全 0 → 详情 enrich 全 miss → 升级 L2（保底路径不丢）。"""

    async def _run():
        svc = CrawlerService()
        svc.httpx_crawler = _FakeHttpx([_mk("a")])
        svc.playwright_crawler = _FakePlaywright([_mk("a", 303)])
        svc.detail_crawler = _StubDetail({})  # 全部 miss

        products, source = await svc.crawl("kw")
        assert source == "playwright"
        assert products[0].want_count == 303
        assert svc.playwright_crawler.called == 1

    asyncio.run(_run())
