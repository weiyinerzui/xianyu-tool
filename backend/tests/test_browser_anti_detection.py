"""L2 浏览器的反指纹与登录态注入测试（P0-1 / P0-2）。

不发起真实网络请求，只验证「浏览器启动参数」与「cookie 注入格式」正确 ——
这是绕过闲鱼两层反爬（指纹层 + 登录态层）的配置基础。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.crawlers.playwright_crawler import PlaywrightCrawler

FAKE_COOKIES = {
    "cookie2": "abc123",
    "unb": "12345678",
    "cna": "xyz",
    "_m_h5_tk": "tk_1699999999",
}


def test_headless_disabled_by_default():
    """闲鱼会识别 headless Chromium 并返回「非法访问」，因此必须默认关闭。"""
    kwargs = PlaywrightCrawler()._launch_kwargs()
    assert kwargs["headless"] is False, "headless 必须默认关闭"


def test_stealth_args_present():
    """反指纹启动参数必须到位。"""
    args = PlaywrightCrawler()._launch_kwargs()["args"]
    joined = " ".join(args)
    assert "AutomationControlled" in joined
    assert "--lang=zh-CN" in joined
    assert "--window-size=1440,900" in joined


def test_cookies_injected_as_storage_state():
    """cookie 必须转成 Playwright storage_state，且域名为 .goofish.com。"""
    kwargs = PlaywrightCrawler()._context_kwargs(FAKE_COOKIES)
    assert "storage_state" in kwargs, "cookie 未注入 storage_state"
    cookies = kwargs["storage_state"]["cookies"]
    assert len(cookies) == len(FAKE_COOKIES)
    for ck in cookies:
        assert ck["domain"] == ".goofish.com"
        assert ck["path"] == "/"


def test_no_cookies_means_no_storage_state():
    """无 cookie 时不应注入空 storage_state（否则覆盖浏览器默认状态）。"""
    kwargs = PlaywrightCrawler()._context_kwargs({})
    assert "storage_state" not in kwargs


def test_persistent_profile_excludes_storage_state():
    """持久化 profile 自带 cookie 存储，与 storage_state 互斥。

    两者同时传给 Playwright 会直接抛错，因此必须互斥。
    """
    import os

    os.environ["XIANYU_OPS_CRAWLER_USER_DATA_DIR"] = "/tmp/pw_profile_unit_test"
    try:
        import importlib

        import app.config

        importlib.reload(app.config)
        kwargs = PlaywrightCrawler()._context_kwargs(FAKE_COOKIES)
        assert "user_data_dir" in kwargs
        assert "storage_state" not in kwargs, "profile 与 storage_state 不能同时存在"
    finally:
        del os.environ["XIANYU_OPS_CRAWLER_USER_DATA_DIR"]
        import importlib

        import app.config

        importlib.reload(app.config)


def test_context_has_realistic_fingerprint():
    """context 必须伪装成真实中文桌面浏览器。"""
    kwargs = PlaywrightCrawler()._context_kwargs({})
    assert kwargs["locale"] == "zh-CN"
    assert kwargs["timezone_id"] == "Asia/Shanghai"
    assert kwargs["viewport"]["width"] == 1440
    assert "Chrome" in kwargs["user_agent"]


if __name__ == "__main__":
    test_headless_disabled_by_default()
    test_stealth_args_present()
    test_cookies_injected_as_storage_state()
    test_no_cookies_means_no_storage_state()
    test_persistent_profile_excludes_storage_state()
    test_context_has_realistic_fingerprint()
    print("✅ test_browser_anti_detection: 全部通过")