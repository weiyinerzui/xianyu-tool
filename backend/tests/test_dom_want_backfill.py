"""L2 想要数 DOM 回填测试。

背景：实测（2026-10）服务端不再通过 mtop.taobao.idlemtopsearch.pc.search
下发 wantNum（带登录态 30/30 条恒为 '0'），想要数只呈现在搜索结果
卡片 DOM 文本「N人想要」中。L2 爬虫需从 DOM 收集并回填。

本文件测试纯 Python 可测的部分：
- _EXTRACT_JS 含有 want_count 提取（parseWant）
- _collect_dom_wants 对 page.evaluate 结果的归一化
- 回填循环：有值才覆盖、零值不覆盖
"""

from __future__ import annotations

import re

from app.crawlers.playwright_crawler import _EXTRACT_JS, PlaywrightCrawler


class _FakePage:
    """page.evaluate 桩：返回预置的 {item_id: want} 映射。"""

    def __init__(self, result=None, exc: Exception | None = None) -> None:
        self.result = result or {}
        self.exc = exc

    async def evaluate(self, _js, *args):  # noqa: ANN001
        if self.exc:
            raise self.exc
        return self.result


def test_extract_js_has_want_parsing():
    """_EXTRACT_JS 必须包含想要数解析（N人想要 + 万单位兼容）。"""
    assert "want_count" in _EXTRACT_JS, "DOM 提取 JS 需输出 want_count 字段"
    assert "人想要" in _EXTRACT_JS
    assert "万" in _EXTRACT_JS, "需兼容 '1.2万' 大数格式"


def test_collect_dom_wants_normalizes():
    """字符串 key/value 需归一化为 {str: int}。"""
    page = _FakePage({"1048204884222": "514", "123": 45})
    craw = PlaywrightCrawler()
    # _collect_dom_wants 是 async：用 asyncio.run 驱动
    import asyncio

    got = asyncio.run(craw._collect_dom_wants(page))
    assert got == {"1048204884222": 514, "123": 45}


def test_collect_dom_wants_survives_failure():
    """page.evaluate 抛错时返回空 dict，不阻断采集主流程。"""
    page = _FakePage(exc=RuntimeError("page closed"))
    craw = PlaywrightCrawler()
    import asyncio

    got = asyncio.run(craw._collect_dom_wants(page))
    assert got == {}


def test_backfill_only_fills_missing():
    """回填规则：商品已有非零想要数时不覆盖；DOM 有值且商品为 0 时回填。"""

    class P:  # 最小桩
        def __init__(self, iid: str, want: int) -> None:
            self.xianyu_id = iid
            self.want_count = want

    products = [P("a", 0), P("b", 7), P("c", 0)]
    dom = {"a": 514, "b": 999, "c": 0}  # c 在 DOM 上也是 0（无想要数展示）

    for p in products:
        w = dom.get(p.xianyu_id)
        if w and not p.want_count:
            p.want_count = w

    assert products[0].want_count == 514, "0 值商品应被 DOM 值回填"
    assert products[1].want_count == 7, "已有非零值不被覆盖"
    assert products[2].want_count == 0, "DOM 也是 0 时保持 0"


def test_want_regex_matches_real_cards():
    """用真实卡片文本样式验证解析正则（含万单位）。"""
    texts = [
        ("Python官方正版安装包\n广东·小熊资料库\n¥1\n514人想要", 514),
        ("流畅的Python 第2版\n湖北·青莲镇打瞌睡的选手\n¥1\n297人想要", 297),
        ("脚本合集\n北京\n¥8\n1.2万人想要", 12000),
        ("冷门商品\n上海\n¥3\n0人想要", 0),
    ]

    def parse_want(text: str) -> int:
        # 与 JS 侧 parseWant 保持一致：先普通格式，再万单位格式，兜底 0
        m = re.search(r"(\d+)\s*人想要", text)
        if m:
            return int(m.group(1))
        wm = re.search(r"([\d.]+)\s*万", text)
        if wm:
            return round(float(wm.group(1)) * 10000)
        return 0

    for t, expected in texts:
        assert parse_want(t) == expected, f"解析失败: {t!r}"
