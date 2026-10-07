"""诊断脚本：检查 mtop 搜索响应中想要数等字段的实际取值 + 登录态是否生效。

用法（在 backend 目录下）：
    python -m scripts.inspect_want_num "python教程"

输出：
1. 本地保存的登录 cookie 有哪些 key（只打名字，不打值，不泄密）
2. 全部结果项里 clickParam.args.wantNum / exContent.want 的取值分布
3. 完整原始响应存 scripts/_sample_response.json 供离线分析
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> None:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "python教程"

    # ---- 0) 登录 cookie 检查（只看 key 名） ----
    print("== 登录态检查 ==")
    try:
        from app.services.session_manager import get_session

        sess = get_session()
        if sess.path.exists():
            cookies = sess.get_cookies()
            print(f"cookie 文件: {sess.path}")
            print(f"cookie keys: {sorted(cookies.keys())}")
            for k in ("unb", "cookie2", "_m_h5_tk"):
                print(f"  {k}: {'存在' if cookies.get(k) else '缺失!'}")
        else:
            print(f"!! cookie 文件不存在: {sess.path} —— L1 在匿名模式下采集")
    except Exception as e:  # noqa: BLE001
        print(f"!! 读取登录态失败: {e}")

    # ---- 1) 抓取并捕获原始响应 ----
    import app.crawlers.httpx_crawler as hc

    captured: dict[str, Any] = {}
    orig_parse = hc.parse_search_api_json

    def spy(json_data: dict, category: str = "") -> list:
        captured["raw"] = json_data
        return orig_parse(json_data, category)

    hc.parse_search_api_json = spy

    products = await hc.HttpxCrawler().search(keyword)
    print(f"\n== 关键词: {keyword} | 解析出 {len(products)} 个商品 ==")

    raw = captured.get("raw")
    if not raw:
        print("!! 未捕获到原始响应（可能触发风控/令牌失效，看后端日志）")
        return

    out_path = Path("scripts/_sample_response.json")
    out_path.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完整原始响应已存: {out_path.resolve()}")

    items = raw.get("data", {}).get("resultList", []) or []
    if not items:
        print("resultList 为空")
        return
    print(f"resultList 条数: {len(items)}")

    # ---- 2) 全量字段分布统计 ----
    want_num_vals: Counter = Counter()
    ex_want_vals: Counter = Counter()
    for it in items:
        try:
            args = it["data"]["item"]["main"].get("clickParam", {}).get("args", {})
            want_num_vals[str(args.get("wantNum", "<无此字段>"))] += 1
            ex = it["data"]["item"]["main"].get("exContent", {})
            ex_want_vals[str(ex.get("want", "<无此字段>"))] += 1
        except (KeyError, TypeError):
            want_num_vals["<结构异常>"] += 1

    print("\n-- clickParam.args.wantNum 取值分布（全部条目） --")
    for v, c in want_num_vals.most_common():
        print(f"  {v!r}: {c} 条")
    print("\n-- exContent.want 取值分布（全部条目） --")
    for v, c in ex_want_vals.most_common():
        print(f"  {v!r}: {c} 条")

    # ---- 3) 结论提示 ----
    total_zero = want_num_vals.get("0", 0) + want_num_vals.get("''", 0)
    if len(items) and total_zero == len(items):
        print(
            "\n[结论] 所有条目 wantNum 均为 0/空。结合上面 cookie 检查：\n"
            "  - 若 _m_h5_tk/unb 缺失 → 匿名请求，服务端不下发想要数\n"
            "  - 若 cookie 齐全仍全 0 → 服务端对该请求模式不下发想要数，\n"
            "    需要 L2（playwright 带登录态）对比验证"
        )


if __name__ == "__main__":
    asyncio.run(main())
