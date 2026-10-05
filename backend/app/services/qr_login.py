"""扫码登录服务（P0-3）。

闲鱼搜索接口对未登录请求一律返回 RGV587_ERROR，且搜索结果页在未登录时
根本不渲染（页面停在「加载中」）。因此「拿到登录态」是数据采集的前置条件。

本模块用一个常驻 Playwright 浏览器打开闲鱼登录页，用户用闲鱼 App 扫码，
轮询检测登录成功后把 cookie 落盘，供 L1(httpx 签名) 与 L2(浏览器上下文) 共用。

设计要点：
- 登录窗口是「长驻会话」，不用 asyncio.to_thread 包线程池，
  避免线程池被长任务占满导致后续采集排队。
- 登录态由 session_manager 统一落盘（权限 0600），与现有 import 端点共用。
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

LOGIN_URL = "https://www.goofish.com/login"
QR_URL = "https://www.goofish.com/mini_login.htm?appName=xianyu"

# 登录成功判据：页面出现这些特征即认为已登录
_SUCCESS_MARKERS = ("退出", "我的闲鱼", "发布闲置", "消息")
# 出现登录框则仍未登录
_PENDING_MARKERS = ("扫码登录", "登录", "二维码")

# 登录成功后要保留的 cookie（其余为易变/风控字段，不必长期存）
_KEEP_KEYS = (
    "cookie2", "unb", "cna", "tracknick", "_m_h5_tk",
    "sgcookie", "t", "isg", "l", "xlly_s",
)


def _looks_logged_in(text: str) -> bool:
    """根据页面文本判断是否登录成功。"""
    has_success = any(m in text for m in _SUCCESS_MARKERS)
    has_login_form = "扫码登录" in text or "立即登录" in text
    return has_success and not has_login_form


class QRLoginSession:
    """一次扫码登录会话（长驻浏览器 + 轮询检测）。"""

    def __init__(self, timeout: int = 180) -> None:
        self.timeout = timeout
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._started_at: float = 0.0

    async def start(self) -> dict[str, Any]:
        """打开登录页并返回登录地址。"""
        from playwright.async_api import async_playwright

        from app.config import settings
        from app.services.playwright_runtime import browser_launch_kwargs

        self._playwright = await async_playwright().start()
        launch_kwargs = browser_launch_kwargs(self._playwright.chromium)
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        self._page = await self._context.new_page()
        # 打开 PC 端登录页（含二维码）
        await self._page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        await self._page.wait_for_timeout(2000)
        self._started_at = asyncio.get_event_loop().time()
        logger.info("QR login page opened (headless=%s)", launch_kwargs.get("headless"))
        return {
            "ok": True,
            "login_url": LOGIN_URL,
            "headless": launch_kwargs.get("headless"),
            "hint": "请在打开的浏览器窗口中用闲鱼 App 扫码登录；本工具会自动检测登录状态",
        }

    async def wait_for_login(self) -> dict[str, Any]:
        """轮询等待登录成功，成功后落盘 cookie。"""
        import time

        from app.services.session_manager import get_session

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self._page is None or self._page.is_closed():
                return {"ok": False, "reason": "浏览器窗口已关闭"}
            try:
                text = await self._page.evaluate("document.body?.innerText || ''")
            except Exception as e:  # noqa: BLE001
                logger.debug("读取页面失败：%s", e)
                await asyncio.sleep(1.5)
                continue

            if _looks_logged_in(text):
                cookies = await self._context.cookies()
                kept = {
                    c["name"]: c["value"]
                    for c in cookies
                    if c["name"] in _KEEP_KEYS and c.get("value")
                }
                if not kept:
                    return {"ok": False, "reason": "检测到登录，但未获取到关键 cookie"}
                get_session().save(kept)
                logger.info("登录成功，保存 %d 项 cookie", len(kept))
                return {"ok": True, "cookie_count": len(kept), "keys": sorted(kept.keys())}

            await asyncio.sleep(2.0)

        return {"ok": False, "reason": f"等待超时（{self.timeout}s）"}

    async def close(self) -> None:
        for obj, meth in (
            (self._context, "close"),
            (self._browser, "close"),
            (self._playwright, "stop"),
        ):
            try:
                if obj is not None:
                    await getattr(obj, meth)()
            except Exception as e:  # noqa: BLE001
                logger.debug("关闭 %s 失败：%s", type(obj).__name__, e)
        self._page = self._context = self._browser = self._playwright = None


# 模块级单例：同一时间只允许一个登录会话
_session: QRLoginSession | None = None


def get_qr_session() -> QRLoginSession:
    global _session
    if _session is None:
        _session = QRLoginSession()
    return _session


def is_running() -> bool:
    return _session is not None and _session._page is not None


async def close_qr_session() -> None:
    global _session
    if _session is not None:
        await _session.close()
    _session = None