"""浏览器运行时：集中管理反指纹启动参数（P0-1）。

抽取为独立模块的原因：L2 采集器与扫码登录服务都需要「能通过闲鱼指纹检测」的
浏览器启动方式，逻辑必须一致，否则登录能过但采集被拦（或反之）。

实测结论：闲鱼会识别 headless Chromium 并直接返回「非法访问」页；
改为 headless=False（Linux 无显示器时套 xvfb）后该层拦截被绕过。
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from typing import Any

logger = logging.getLogger(__name__)

# 反指纹启动参数：抹掉自动化痕迹，并按真实桌面环境渲染
STEALTH_ARGS = [
    "--no-sandbox",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--window-size=1440,900",
    "--lang=zh-CN",
]

# 抹除 navigator.webdriver 等常见自动化指纹
STEALTH_INIT_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'] });
window.chrome = window.chrome || { runtime: {} };
"""


def needs_xvfb() -> bool:
    """Linux 下无 DISPLAY 且未关闭 headless 时，需要 xvfb 虚拟显示器。"""
    if sys.platform != "linux":
        return False
    from app.config import settings

    if not settings.crawler_auto_xvfb:
        return False
    if settings.crawler_headless:
        return False
    return not os.environ.get("DISPLAY")


def pick_proxy() -> dict[str, str] | None:
    """从代理池取一个代理，降低单 IP 触发风控的概率。"""
    from app.config import settings

    proxies = [p.strip() for p in settings.crawler_proxies.split(",") if p.strip()]
    if not proxies:
        return None
    return {"server": proxies[0]}


_XVFB_HINT = (
    "已配置 crawler_headless=False（闲鱼会识别 headless 浏览器并返回「非法访问」），"
    "但当前环境没有 X server。请任选其一：\n"
    "  1) 用虚拟显示器启动： xvfb-run -a uvicorn app.main:app --port 8000\n"
    "  2) 安装 xvfb 后用虚拟显示器： apt install xvfb\n"
    "  3) 临时改回 headless： export XIANYU_OPS_CRAWLER_HEADLESS=true"
    "（会被闲鱼指纹识别，采集可能返回 0 条）"
)


def assert_display_available() -> None:
    """启动浏览器前检查 X server 可用性，避免等 30s 超时才报晦涩错误。"""
    if not needs_xvfb():
        return
    if shutil.which("Xvfb") is None:
        raise RuntimeError("未检测到 Xvfb，无法创建虚拟显示器。\n" + _XVFB_HINT)
    logger.info("无 DISPLAY，但已安装 Xvfb：请用 xvfb-run 启动本服务")


def browser_launch_kwargs(_browser_type: Any = None, attempt: int = 0) -> dict[str, Any]:
    """组装 chromium.launch() 参数（headless 配置化 + 反指纹 + 代理）。"""
    from app.config import settings

    assert_display_available()

    kwargs: dict[str, Any] = {
        "headless": settings.crawler_headless,
        "args": list(STEALTH_ARGS),
    }
    proxies = [p.strip() for p in settings.crawler_proxies.split(",") if p.strip()]
    if proxies:
        idx = attempt % len(proxies)
        kwargs["proxy"] = {"server": proxies[idx]}
        logger.info("使用代理 %s", proxies[idx])

    if needs_xvfb():
        logger.info(
            "检测到无 DISPLAY 且 crawler_headless=False："
            "请用 xvfb-run 启动（如 xvfb-run -a uvicorn app.main:app），"
            "否则浏览器无法创建窗口"
        )
    return kwargs


def context_kwargs(cookies: dict[str, str] | None = None) -> dict[str, Any]:
    """组装 browser.new_context() 参数（注入登录态 + 伪装真实浏览器）。"""
    import random

    from app.config import settings

    kwargs: dict[str, Any] = {
        "user_agent": random.choice(
            [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            ]
        ),
        "viewport": {"width": 1440, "height": 900},
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
    }
    if cookies:
        kwargs["storage_state"] = {
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
    if settings.crawler_user_data_dir:
        kwargs["user_data_dir"] = settings.crawler_user_data_dir
    return kwargs