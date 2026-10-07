"""L2 直调诊断：复现 PlaywrightCrawler 完整流程并逐步输出中间状态。

用法（backend 目录）：
    python -m scripts.diag_l2_crawl "python教程"

与 scripts/inspect_want_l2.py 的区别：那个用独立浏览器验证数据源；
这个直接调 PlaywrightCrawler（就是线上采集用的代码），失败时打印
所有中途信号：cookie 注入、页面标记、API 拦截数、DOM 提取数、异常。

之前已验证：inspect_want_l2 在同机同 cookie 能拿到 30 条 + DOM 想要数。
若本脚本失败，说明问题出在 PlaywrightCrawler 自身流程。
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 打开应用日志，让 logger.info 直接可见
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main() -> None:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "python教程"
    print(f"== L2 直调诊断：{keyword} ==")

    from app.crawlers.playwright_crawler import PlaywrightCrawler

    craw = PlaywrightCrawler()

    # 前置检查：cookie 与配置
    cookies = craw._load_cookies()
    print(f"[前置] 登录 cookie: {len(cookies)} 项 {sorted(cookies.keys())[:6]}...")
    from app.config import settings

    print(f"[前置] headless={settings.crawler_headless}, max_pages={settings.crawler_search_max_pages}")
    print(f"[前置] user_data_dir={settings.crawler_user_data_dir!r}, proxies={settings.crawler_proxies!r}")

    # 直调 search()（即线上路径；它在 to_thread 里自己开事件循环）
    print("\n[执行] 调用 craw.search() ...")
    try:
        products = await craw.search(keyword)
    except Exception as e:  # noqa: BLE001
        print(f"\n!! search 抛异常: {type(e).__name__}: {e}")
        return

    print(f"\n[结果] {len(products)} 个商品")
    if not products:
        print("空结果 —— 请把上面 [前置] 与日志一起反馈")
        return

    zero = sum(1 for p in products if p.want_count == 0)
    print(f"[结果] 想要数: {len(products) - zero}/{len(products)} 个非零")
    for p in sorted(products, key=lambda x: -x.want_count)[:5]:
        print(f"   want={p.want_count:>5}  {p.title[:40]}")


if __name__ == "__main__":
    asyncio.run(main())
