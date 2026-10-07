"""L2 诊断脚本：用带登录态的真实浏览器，定位想要数的真实来源。

用法（在 backend 目录下，Windows 直接跑，有显示器）：
    python -m scripts.inspect_want_l2 "python教程"

做三件事：
1. 注入登录 cookie 打开 goofish.com 搜索页，捕获 mtop 搜索响应
   （dump 第一个条目的全部数值字段，找"想要"藏在哪）
2. 扫描 DOM 文本中的 "N人想要" 数字分布
3. 对比两者，输出结论：API字段没带了 vs DOM能拿到
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

API_FRAG = "mtop.taobao.idlemtopsearch.pc.search"


def _walk_numbers(obj: Any, path: str = "$", out: list | None = None) -> list:
    """收集所有路径上值为纯数字字符串/int 的字段。"""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
                out.append((p, v))
            _walk_numbers(v, p, out)
    elif isinstance(obj, list) and obj:
        _walk_numbers(obj[0], f"{path}[0]", out)
    return out


async def main() -> None:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "python教程"
    print(f"== L2 诊断：{keyword} ==")

    from urllib.parse import quote

    from playwright.async_api import async_playwright

    from app.services.playwright_runtime import browser_launch_kwargs, context_kwargs
    from app.services.session_manager import get_session

    # 登录 cookie
    cookies: dict[str, str] = {}
    sess = get_session()
    if sess.path.exists():
        cookies = sess.get_cookies()
    print(f"登录 cookie: {len(cookies)} 项")
    if not cookies:
        print("!! 无登录 cookie，结果仅代表匿名模式")

    captured: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(**browser_launch_kwargs(p.chromium))
        ctx = await browser.new_context(
            **context_kwargs(cookies),
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = await ctx.new_page()

        async def on_response(response):
            if API_FRAG in response.url:
                try:
                    captured.append(await response.json())
                except Exception as e:  # noqa: BLE001
                    print(f"!! 响应解析失败: {e}")

        page.on("response", on_response)

        url = f"https://www.goofish.com/search?q={quote(keyword)}"
        print(f"打开: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        # ---- 1) DOM 扫描：N人想要 ----
        dom_wants = await page.evaluate(
            """() => {
                const t = document.body?.innerText || '';
                const m = t.match(/(\\d+)人想要/g) || [];
                return m.map(s => parseInt(s));
            }"""
        )
        print(f"\n-- DOM 'N人想要' 命中 {len(dom_wants)} 个 --")
        if dom_wants:
            print(f"   样本: {sorted(dom_wants, reverse=True)[:15]}")
            print(f"   非零数量: {sum(1 for w in dom_wants if w > 0)}/{len(dom_wants)}")

        # ---- 2) mtop 响应分析 ----
        print(f"\n-- 捕获 mtop 搜索响应 {len(captured)} 个 --")
        want_hits: Counter = Counter()
        numeric_sample: list[tuple[str, Any]] = []
        raw_saved = False
        for raw in captured:
            ret = json.dumps(raw.get("ret", []), ensure_ascii=False)
            if "SUCCESS" not in ret:
                print(f"   非 SUCCESS: {ret[:120]}")
                continue
            items = raw.get("data", {}).get("resultList", []) or []
            if items and not raw_saved:
                numeric_sample = _walk_numbers(items[0])
                out = Path("scripts/_l2_sample_response.json")
                out.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"   首个 SUCCESS 响应已存: {out.resolve()}")
                raw_saved = True
            for it in items:
                try:
                    args = it["data"]["item"]["main"].get("clickParam", {}).get("args", {})
                    want_hits[str(args.get("wantNum", "<无>"))] += 1
                except (KeyError, TypeError):
                    want_hits["<结构异常>"] += 1

        print(f"\n-- 浏览器内 mtop wantNum 分布 --")
        for v, c in want_hits.most_common(10):
            print(f"   {v!r}: {c} 条")

        if numeric_sample:
            print(f"\n-- 首条目全部数值字段（前 60 个）--")
            for p_, v in numeric_sample[:60]:
                print(f"   {p_} = {v}")

        # ---- 3) 结论 ----
        print("\n== 结论指引 ==")
        if dom_wants:
            print("DOM 有想要数 → L2 DOM 提取可行（需扩展 _EXTRACT_JS）")
        if want_hits and want_hits.get("0", 0) == sum(want_hits.values()):
            print("浏览器内 mtop 也全 0 → 服务端確实不再通过该接口下发")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
