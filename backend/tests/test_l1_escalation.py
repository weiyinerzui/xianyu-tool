"""L1 数据残缺时升级 L2 的降级策略测试。

背景（2026-10 实测）：闲鱼服务端停止通过 mtop 搜索 API 下发 wantNum。
L1 httpx 即使成功也全部 want_count=0。策略改为：L1 结果想要数全 0
视为数据残缺，继续走 L2（Playwright，DOM 回填想要数）拿完整数据。

项目无 pytest-asyncio，统一用 asyncio.run 驱动（与 test_snapshot_velocity 一致）。
"""

from __future__ import annotations

import asyncio

from app.crawlers.base import CrawledProduct
from app.services.crawler_service import CrawlerService


def _mk(iid: str, want: int = 0) -> CrawledProduct:
    return CrawledProduct(
        xianyu_id=iid, title=f"t{iid}", price=1.0, want_count=want, area="", link=""
    )


class _FakeHttpx:
    def __init__(self, products, exc: Exception | None = None) -> None:
        self.products = products
        self.exc = exc
        self.called = 0

    async def search(self, keyword, category=None):  # noqa: ANN001
        self.called += 1
        if self.exc:
            raise self.exc
        return list(self.products)


class _FakePlaywright:
    def __init__(self, products) -> None:
        self.products = products
        self.called = 0

    async def search(self, keyword, category=None):  # noqa: ANN001
        self.called += 1
        return list(self.products)


def test_l1_all_zero_want_escalates_to_l2():
    """L1 成功但想要数全 0 → 升级 L2，返回 L2 数据。"""

    async def _run():
        svc = CrawlerService()
        svc.httpx_crawler = _FakeHttpx([_mk("a"), _mk("b")])  # 全 0
        svc.playwright_crawler = _FakePlaywright([_mk("a", 514), _mk("b", 297)])

        products, source = await svc.crawl("kw")
        assert source == "playwright"
        assert len(products) == 2
        assert products[0].want_count == 514
        assert svc.httpx_crawler.called == 1
        assert svc.playwright_crawler.called == 1

    asyncio.run(_run())


def test_l1_with_want_data_wins():
    """L1 有非零想要数（未来服务端恢复下发）→ 不触发 L2，快速返回。"""

    async def _run():
        svc = CrawlerService()
        svc.httpx_crawler = _FakeHttpx([_mk("a", 3), _mk("b", 0)])  # 部分非零
        svc.playwright_crawler = _FakePlaywright([_mk("a", 5)])

        products, source = await svc.crawl("kw")
        assert source == "httpx"
        assert svc.playwright_crawler.called == 0

    asyncio.run(_run())


def test_l1_exception_falls_to_l2():
    """L1 抛错 → 常规降级 L2。"""

    async def _run():
        svc = CrawlerService()
        svc.httpx_crawler = _FakeHttpx([], exc=RuntimeError("RGV587 风控"))
        svc.playwright_crawler = _FakePlaywright([_mk("a", 5)])

        products, source = await svc.crawl("kw")
        assert source == "playwright"
        assert products[0].want_count == 5

    asyncio.run(_run())
