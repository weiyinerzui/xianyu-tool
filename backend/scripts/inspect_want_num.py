"""诊断脚本：检查 mtop 搜索响应中想要数/浏览数等字段的实际位置。

用法（在 backend 目录下）：
    python -m scripts.inspect_want_num "python教程"

原理：monkeypatch parse_search_api_json，捕获解析前的原始 JSON，
再全字段扫描 want/view/click 相关字段，定位 wantNum 是否换了位置/改名。

前提：已扫码登录（cookies.json 存在）。
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def find_fields(obj: Any, pattern: re.Pattern, path: str = "$", out: list | None = None) -> list:
    """递归找出所有名字匹配正则的字段路径与值（列表只深入前 3 个元素）。"""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            if pattern.search(k):
                out.append((p, v if not isinstance(v, (dict, list)) else f"<{type(v).__name__}>"))
            find_fields(v, pattern, p, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:3]):
            find_fields(v, pattern, f"{path}[{i}]", out)
    return out


async def main() -> None:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "python教程"

    import app.crawlers.httpx_crawler as hc

    captured: dict[str, Any] = {}
    orig_parse = hc.parse_search_api_json

    def spy(json_data: dict, category: str = "") -> list:
        captured["raw"] = json_data
        return orig_parse(json_data, category)

    hc.parse_search_api_json = spy

    products = await hc.HttpxCrawler().search(keyword)
    print(f"== 关键词: {keyword} | 解析出 {len(products)} 个商品 ==")

    raw = captured.get("raw")
    if not raw:
        print("!! 未捕获到原始响应（可能触发风控/令牌失效，看后端日志）")
        return

    # 存一份完整原始响应供离线分析
    out_path = Path("scripts/_sample_response.json")
    out_path.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完整原始响应已存: {out_path.resolve()}")

    items = raw.get("data", {}).get("resultList", []) or []
    if not items:
        print("resultList 为空")
        return
    print(f"resultList 条数: {len(items)}")

    # 1) 全字段扫描
    for pat_str in [r"want", r"view", r"click", r"sold|cnt$|count"]:
        print(f"\n-- 模式 {pat_str!r} 命中（结果[0]） --")
        hits = find_fields(items[0], re.compile(pat_str, re.I))
        for p, v in hits or []:
            print(f"  {p} = {v!r}")
        if not hits:
            print("  （无）")

    # 2) 结构 keys
    first = items[0]
    main_node = first.get("data", {}).get("item", {}).get("main", {})
    print("\n-- 结果[0].data.item.main keys --")
    print(sorted(main_node.keys()))
    print("\n-- clickParam.args --")
    print(json.dumps(main_node.get("clickParam", {}).get("args", {}), ensure_ascii=False, indent=1)[:1500])

    # 3) 顺带验证解析结果中的想要数
    zero_want = sum(1 for p in products if p.want_count == 0)
    print(f"\n解析结果: {zero_want}/{len(products)} 个商品 want_count=0")


if __name__ == "__main__":
    asyncio.run(main())
