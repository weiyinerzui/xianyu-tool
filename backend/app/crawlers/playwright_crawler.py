"""L2 采集器：Playwright 浏览器自动化（抗风控降级方案）。

参考 goofish-cli commands/search/search.py 的 DOM 提取思路，
以及 xianyu-tool/backend/app/crawlers/playwright_crawler.py 的持久化上下文。

反爬对抗（P0-1 / P0-2）——闲鱼有两层拦截，必须都突破才有数据：
  1. 浏览器指纹层：headless Chromium 被识别，页面直接返回「非法访问」。
     解决办法：headless=False（配置项 crawler_headless），Linux 无显示器时
     套 xvfb-run；叠加 stealth 启动参数与 webdriver 抹除。
  2. 业务风控层：mtop 搜索接口校验登录态，未登录一律 RGV587。
     解决办法：把 session_manager 的 cookie 注入浏览器上下文。

Windows 兼容修复：
uvicorn --reload 在 Windows 上会用 SelectorEventLoop（不支持子进程），
导致 Playwright 拉起浏览器 driver 子进程时抛 NotImplementedError。
解决办法：把整个 Playwright 流程放进独立工作线程，线程内新建
ProactorEventLoop（Windows）运行，与 uvicorn 主事件循环彻底解耦。
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import sys
from typing import Any
from urllib.parse import quote

from app.crawlers.base import BaseCrawler, CrawledProduct, parse_price_str
from app.services.playwright_runtime import (
    STEALTH_INIT_JS,
    browser_launch_kwargs,
    context_kwargs,
    needs_xvfb,
)

logger = logging.getLogger(__name__)

# 页面内执行的 JS：提取搜索结果卡片
_EXTRACT_JS = r"""
(limit) => (async () => {
  const wait = (ms) => new Promise(r => setTimeout(r, ms));
  const waitFor = async (predicate, timeoutMs = 8000) => {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (predicate()) return true;
      await wait(150);
    }
    return false;
  };
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const sel = {
    card: 'a[href*="/item?id="]',
    title: '[class*="row1-wrap-title"], [class*="main-title"]',
    priceWrap: '[class*="price-wrap"]',
    priceNum: '[class*="number"]',
    priceDec: '[class*="decimal"]',
    sellerWrap: '[class*="row4-wrap-seller"]',
    sellerText: '[class*="seller-text"]',
  };
  await waitFor(() => {
    const t = document.body?.innerText || '';
    return Boolean(
      document.querySelector(sel.card)
      || /请先登录|登录后|验证码|安全验证|暂无相关宝贝/.test(t)
    );
  });
  // 从卡片文本解析 "N人想要"（服务端已不再通过 mtop API 下发该字段，仅 DOM 呈现）
  const parseWant = (text) => {
    const m = /(\d+)\s*人想要/.exec(text || '');
    if (m) return parseInt(m[1], 10);
    const t = clean(text || '').replace(/,/g, '');
    // 兼容 "1.2万" 格式
    const wm = /([\d.]+)\s*万/.exec(t);
    if (wm) return Math.round(parseFloat(wm[1]) * 10000);
    return 0;
  };
  const items = Array.from(document.querySelectorAll(sel.card))
    .slice(0, limit)
    .map((card) => {
      const href = card.href || card.getAttribute('href') || '';
      const title = clean(card.querySelector(sel.title)?.textContent || '');
      const pw = card.querySelector(sel.priceWrap);
      const pn = clean(pw?.querySelector(sel.priceNum)?.textContent || '');
      const pd = clean(pw?.querySelector(sel.priceDec)?.textContent || '');
      const loc = clean(card.querySelector(sel.sellerWrap)?.querySelector(sel.sellerText)?.textContent || '');
      return {
        title,
        url: href,
        price: clean('¥' + pn + pd).replace(/^¥\s*$/, ''),
        location: loc,
        want_count: parseWant(card.innerText),
      };
    });
  return { items, empty: /暂无相关宝贝|没有找到/.test(document.body?.innerText || '') };
});
"""

# 闲鱼「非法访问」拦截页特征
_BLOCK_MARKERS = ("非法访问", "请使用正常浏览器访问")

# 未登录时搜索结果不渲染，页面停在「加载中」并弹出登录引导
_LOGIN_PROMPT = "登录后可以更懂你"


def _item_id_from_url(url: str) -> str:
    m = re.search(r"[?&]id=(\d+)", url or "")
    return m.group(1) if m else ""


def _new_event_loop() -> asyncio.AbstractEventLoop:
    """创建支持子进程的事件循环（Windows 用 ProactorEventLoop）。"""
    if sys.platform == "win32":
        return asyncio.ProactorEventLoop()
    return asyncio.new_event_loop()


def _needs_xvfb() -> bool:
    """Linux 下无 DISPLAY 且未关闭 headless 时，需要 xvfb 虚拟显示器。"""
    if sys.platform != "linux":
        return False
    from app.config import settings

    if not settings.crawler_auto_xvfb:
        return False
    if settings.crawler_headless:
        return False
    return not os.environ.get("DISPLAY")


class PlaywrightCrawler(BaseCrawler):
    """L2: Playwright 浏览器采集，抗风控。"""

    def __init__(self) -> None:
        super().__init__()
        self._cookie_hint: str | None = None

    async def search(self, keyword: str, category: str | None = None) -> list[CrawledProduct]:
        # 放进工作线程运行，规避 Windows SelectorEventLoop 不支持子进程的限制
        return await asyncio.to_thread(self._search_in_thread, keyword, category)

    def _search_in_thread(
        self, keyword: str, category: str | None
    ) -> list[CrawledProduct]:
        """在工作线程内新建事件循环运行 Playwright 协程。"""
        loop = _new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._search_async(keyword, category))
        finally:
            try:
                loop.close()
            except Exception:  # noqa: BLE001
                pass
            asyncio.set_event_loop(None)

    async def _collect_dom_wants(self, page: Any) -> dict[str, int]:
        """从当前页 DOM 收集 {item_id: 想要数}。

        服务端已不再通过 mtop API 下发 wantNum（实测 30/30 恒为 0），
        想要数只呈现在卡片文本 "N人想要" 中。失败不阻断主流程。
        """
        js = r"""
        () => {
          const out = {};
          document.querySelectorAll('a[href*="/item?id="]').forEach((card) => {
            const href = card.href || card.getAttribute('href') || '';
            const m = /[?&]id=(\d+)/.exec(href);
            if (!m) return;
            const t = (card.innerText || '').replace(/\s+/g, ' ');
            const w = /(\d+)\s*人想要/.exec(t);
            if (w) out[m[1]] = parseInt(w[1], 10);
          });
          return out;
        }
        """
        try:
            result = await page.evaluate(js)
            return {str(k): int(v) for k, v in (result or {}).items()}
        except Exception as e:  # noqa: BLE001
            logger.debug("DOM 想要数收集失败：%s", e)
            return {}

    def _load_cookies(self) -> dict[str, str]:
        """加载登录态 cookie（不存在时返回空 dict，不阻断采集）。"""
        try:
            from app.services.session_manager import get_session

            session = get_session()
            if session.path.exists():
                cookies = session.get_cookies()
                if cookies:
                    logger.info("注入登录态 cookie：%d 项", len(cookies))
                    return cookies
        except Exception as e:  # noqa: BLE001
            logger.debug("cookie 加载失败：%s", e)
        return {}

    @staticmethod
    def _to_storage_state(cookies: dict[str, str]) -> dict[str, Any]:
        """把 {name: value} 转成 Playwright storage_state 格式。"""
        return {
            "cookies": [
                {
                    "name": name,
                    "value": value,
                    "domain": ".goofish.com",
                    "path": "/",
                }
                for name, value in cookies.items()
            ],
            "origins": [],
        }

    def _launch_kwargs(self) -> dict[str, Any]:
        """组装 launch 参数（headless 配置化 + 反指纹 + 代理轮换）。"""
        return browser_launch_kwargs(attempt=self._consecutive_failures)

    def _context_kwargs(self, cookies: dict[str, str]) -> dict[str, Any]:
        """组装 context 参数（注入登录态 + 伪装成真实桌面浏览器）。"""
        kwargs = context_kwargs(cookies)
        if kwargs.get("user_data_dir"):
            # 持久化 profile 自带 cookie 存储，不能再传 storage_state
            kwargs.pop("storage_state", None)
        if cookies and not kwargs.get("user_data_dir"):
            kwargs["storage_state"] = self._to_storage_state(cookies)
        # 注意：Chromium 内核必须配 Chrome 系 UA——Firefox UA 会与
        # TLS/JS 指纹矛盾，反而暴露自动化痕迹。这里从父类 UA 池中
        # 过滤出 Chrome 系再随机。
        kwargs["user_agent"] = random.choice(
            [ua for ua in self.USER_AGENTS if "Chrome" in ua and "Firefox" not in ua]
        )
        return kwargs

    async def _search_async(
        self, keyword: str, category: str | None = None
    ) -> list[CrawledProduct]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright not installed")
            return []

        from app.config import settings
        from app.crawlers.base import parse_search_api_json

        products: list[CrawledProduct] = []
        seen_ids: set[str] = set()
        url = f"https://www.goofish.com/search?q={quote(keyword)}"
        max_pages = max(1, settings.crawler_search_max_pages)

        if needs_xvfb():
            logger.info("无 DISPLAY 且非 headless，启用 xvfb 虚拟显示器")

        try:
            async with async_playwright() as p:
                launch_kwargs = self._launch_kwargs()
                context_kwargs = self._context_kwargs(self._load_cookies())

                # 持久化 profile 需要 launch_persistent_context（自带 context，不再 new_context）
                user_data_dir = context_kwargs.pop("user_data_dir", None)
                browser = None
                if user_data_dir:
                    browser_ctx = await p.chromium.launch_persistent_context(
                        user_data_dir, **launch_kwargs, **context_kwargs
                    )
                    page = browser_ctx.pages[0] if browser_ctx.pages else await browser_ctx.new_page()
                else:
                    browser = await p.chromium.launch(**launch_kwargs)
                    browser_ctx = await browser.new_context(**context_kwargs)
                    page = await browser_ctx.new_page()
                await page.add_init_script(STEALTH_INIT_JS)

                # 拦截搜索 API 响应（优先用 API JSON，字段更全）
                api_products: list[CrawledProduct] = []

                async def on_response(response):
                    if "mtop.taobao.idlemtopsearch.pc.search" in response.url:
                        try:
                            data = await response.json()
                            parsed = parse_search_api_json(data, category or "")
                            for p_ in parsed:
                                if p_.xianyu_id and p_.xianyu_id not in seen_ids:
                                    seen_ids.add(p_.xianyu_id)
                                    api_products.append(p_)
                        except Exception:  # noqa: BLE001
                            pass

                page.on("response", on_response)

                # 首页：domcontentloaded 比 networkidle 更稳（页面有长连接时 networkidle 会超时）
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(4000)

                # 在整页文本中判断标记，避免登录引导出现在页面尾部而漏判
                flags = await page.evaluate(
                    """(markers) => {
                        const t = document.body?.innerText || '';
                        const hit = {};
                        for (const m of markers) hit[m] = t.indexOf(m) >= 0;
                        return hit;
                    }""",
                    list(_BLOCK_MARKERS) + [_LOGIN_PROMPT, "加载中"],
                )

                # 检测「非法访问」拦截页 —— 明确失败优于静默返回空
                if any(flags.get(m) for m in _BLOCK_MARKERS):
                    raise RuntimeError(
                        "被闲鱼反爬拦截（非法访问页）。"
                        "请确认已导入登录 cookie，或配置代理池 crawler_proxies"
                    )

                if api_products:
                    logger.info("PlaywrightCrawler(API拦截): %d products", len(api_products))
                    # 拷贝而非引用！翻页循环里 api_products.clear() 复用采集缓冲，
                    # 引用赋值会让 products 一起被清空（实测导致 30 条数据得而复失、
                    # 翻页循环因 products 为空提前 break）
                    products = list(api_products)
                else:
                    # 未登录时结果不渲染（页面停在「加载中」并弹登录引导）。
                    # 这时静默返回空列表会让用户以为"该关键词没爆款"，必须显式报错。
                    if flags.get(_LOGIN_PROMPT) or flags.get("加载中"):
                        raise RuntimeError(
                            "搜索结果未渲染：闲鱼要求登录后才返回数据。"
                            "请先通过 POST /api/v1/session/import 导入登录 cookie，"
                            "或用 POST /api/v1/session/qr-login 扫码登录"
                        )
                # 无论走 API 还是 DOM 路径，都从 DOM 收集一次"想要数"：
                # 服务端已不再通过 mtop API 下发 wantNum（30/30 条恒为 0），
                # 该数据现在只呈现在页面卡片文本（"N人想要"）中。
                dom_wants = await self._collect_dom_wants(page)
                if dom_wants and products:
                    filled = 0
                    for p_ in products:
                        w = dom_wants.get(p_.xianyu_id)
                        if w and not p_.want_count:
                            p_.want_count = w
                            filled += 1
                    logger.info(
                        "PlaywrightCrawler(想要数回填): DOM %d 项, 回填 %d/%d 商品",
                        len(dom_wants), filled, len(products),
                    )
                if not products:
                    payload = await page.evaluate(_EXTRACT_JS, 30)
                    items = payload.get("items", []) if isinstance(payload, dict) else []
                    for it in items:
                        iid = _item_id_from_url(it.get("url", ""))
                        if not iid or iid in seen_ids:
                            continue
                        seen_ids.add(iid)
                        products.append(CrawledProduct(
                            xianyu_id=iid,
                            title=it.get("title", ""),
                            price=parse_price_str(it.get("price", "")),
                            area=it.get("location", ""),
                            link=it.get("url", ""),
                            category=category or "",
                        ))
                    logger.info("PlaywrightCrawler(DOM): %d products", len(products))

                # 翻页：首屏之外再采 max_pages-1 页，扩大样本量（选品需要样本）
                for page_no in range(2, max_pages + 1):
                    if not products:
                        break
                    api_products.clear()
                    next_url = f"https://www.goofish.com/search?q={quote(keyword)}&page={page_no}"
                    try:
                        await page.goto(next_url, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(3000)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("翻页 %d 失败：%s", page_no, e)
                        break

                    new_items = list(api_products)
                    # 翻页页同样回填 DOM 想要数
                    page_wants = await self._collect_dom_wants(page)
                    for p_ in new_items:
                        w = page_wants.get(p_.xianyu_id)
                        if w and not p_.want_count:
                            p_.want_count = w
                    if not new_items:
                        payload = await page.evaluate(_EXTRACT_JS, 30)
                        for it in (payload.get("items", []) if isinstance(payload, dict) else []):
                            iid = _item_id_from_url(it.get("url", ""))
                            if not iid or iid in seen_ids:
                                continue
                            seen_ids.add(iid)
                            new_items.append(CrawledProduct(
                                xianyu_id=iid,
                                title=it.get("title", ""),
                                price=parse_price_str(it.get("price", "")),
                                area=it.get("location", ""),
                                link=it.get("url", ""),
                                want_count=int(it.get("want_count") or 0),
                                category=category or "",
                            ))
                    logger.info("PlaywrightCrawler(第%d页): +%d products", page_no, len(new_items))
                    products.extend(new_items)

                # browser 为 None 表示用的是 persistent context（其自身即浏览器）
                await browser_ctx.close()
                if browser is not None:
                    await browser.close()
        except Exception as e:  # noqa: BLE001
            logger.error("PlaywrightCrawler failed for '%s': %s", keyword, e)
            self._consecutive_failures += 1
            raise

        return products