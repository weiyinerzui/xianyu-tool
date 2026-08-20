"""登录态管理测试。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.session_manager import SessionManager, SessionError


def _valid_cookies() -> dict[str, str]:
    return {
        "unb": "123456789",
        "_m_h5_tk": "abc123def456",
        "cookie2": "xxx",
        "tracknick": "testuser",
        "cna": "cna123",
    }


def test_save_and_load():
    """保存后能正确加载。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cookies.json"
        sm = SessionManager(path)
        sm.save(_valid_cookies())
        loaded = sm.load()
        assert loaded["unb"] == "123456789"
        assert loaded["_m_h5_tk"] == "abc123def456"


def test_validate_valid():
    """有效 cookie 应通过校验。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cookies.json"
        sm = SessionManager(path)
        sm.save(_valid_cookies())
        assert sm.validate() is True


def test_validate_missing_key():
    """缺必需字段应校验失败。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cookies.json"
        sm = SessionManager(path)
        sm.save({"unb": "123", "cookie2": "xxx"})  # 缺 _m_h5_tk
        assert sm.validate() is False


def test_load_not_exist():
    """文件不存在应抛异常。"""
    with tempfile.TemporaryDirectory() as tmp:
        sm = SessionManager(Path(tmp) / "nope.json")
        try:
            sm.load()
            assert False, "should raise"
        except SessionError:
            pass


def test_load_invalid_json():
    """JSON 格式错误应抛异常。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cookies.json"
        path.write_text("not json", encoding="utf-8")
        sm = SessionManager(path)
        try:
            sm.load()
            assert False, "should raise"
        except SessionError:
            pass


def test_cookie_str():
    """cookie 字符串格式正确。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cookies.json"
        sm = SessionManager(path)
        sm.save({"unb": "123", "_m_h5_tk": "abc"})
        s = sm.get_cookie_str()
        assert "unb=123" in s
        assert "_m_h5_tk=abc" in s
        assert "; " in s


def test_status_masked():
    """status 应脱敏。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cookies.json"
        sm = SessionManager(path)
        sm.save(_valid_cookies())
        status = sm.status()
        assert status["valid"] is True
        assert "***" in status["unb"]
        assert status["unb"] != "123456789"


def test_status_not_exist():
    """文件不存在时 status 应返回 invalid。"""
    with tempfile.TemporaryDirectory() as tmp:
        sm = SessionManager(Path(tmp) / "nope.json")
        status = sm.status()
        assert status["valid"] is False


def test_clear():
    """clear 应删除文件。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cookies.json"
        sm = SessionManager(path)
        sm.save(_valid_cookies())
        assert path.exists()
        sm.clear()
        assert not path.exists()


def test_nested_format():
    """支持 {"cookies": {...}} 嵌套格式。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cookies.json"
        path.write_text(json.dumps({"cookies": _valid_cookies()}), encoding="utf-8")
        sm = SessionManager(path)
        loaded = sm.load()
        assert loaded["unb"] == "123456789"


def test_normalize_devtools_array():
    """支持 DevTools/扩展导出的 [{"name","value"}] 数组格式（用户实际粘贴的格式）。"""
    from app.services.session_manager import normalize_cookies

    data = [
        {"name": "t", "value": "066af7ac273cb5a058f3f655438fa1c8"},
        {"name": "_m_h5_tk", "value": "9cf64adaf538eec2b7697c9a5a348f60_1787229497772"},
        {"name": "unb", "value": "2222760945685"},
        {"name": "tracknick", "value": "xy009827666472"},
    ]
    result = normalize_cookies(data)
    assert result["unb"] == "2222760945685"
    assert result["_m_h5_tk"] == "9cf64adaf538eec2b7697c9a5a348f60_1787229497772"
    assert result["t"] == "066af7ac273cb5a058f3f655438fa1c8"
    assert len(result) == 4


def test_normalize_full_devtools_array():
    """支持带 domain/path 等额外字段的完整 DevTools 导出格式。"""
    from app.services.session_manager import normalize_cookies

    data = [
        {"name": "unb", "value": "123", "domain": ".goofish.com", "path": "/", "httpOnly": True},
        {"name": "_m_h5_tk", "value": "abc_123", "domain": ".goofish.com"},
    ]
    result = normalize_cookies(data)
    assert result == {"unb": "123", "_m_h5_tk": "abc_123"}


def test_normalize_cookie_header_string():
    """支持 Cookie 请求头字符串（document.cookie 输出）。"""
    from app.services.session_manager import normalize_cookies

    s = "unb=123456789; _m_h5_tk=abc123def456_1700000000000; tracknick=test"
    result = normalize_cookies(s)
    assert result["unb"] == "123456789"
    assert result["tracknick"] == "test"


def test_normalize_json_string():
    """支持 JSON 的字符串形式（前端直接粘贴原文）。"""
    from app.services.session_manager import normalize_cookies

    result = normalize_cookies(json.dumps([{"name": "unb", "value": "9"}]))
    assert result == {"unb": "9"}
    result2 = normalize_cookies(json.dumps({"unb": "9", "_m_h5_tk": "x"}))
    assert result2["unb"] == "9"


def test_normalize_nested_array():
    """支持 {"cookies": [数组]} 包装格式。"""
    from app.services.session_manager import normalize_cookies

    result = normalize_cookies({"cookies": [{"name": "unb", "value": "7"}]})
    assert result == {"unb": "7"}


def test_normalize_invalid():
    """非法输入应抛 SessionError。"""
    import pytest

    from app.services.session_manager import SessionError, normalize_cookies

    with pytest.raises(SessionError):
        normalize_cookies(12345)
    with pytest.raises(SessionError):
        normalize_cookies([{"foo": "bar"}])  # 无 name/value
    with pytest.raises(SessionError):
        normalize_cookies("no equals sign here")


def test_load_array_format_file():
    """load() 也应兼容数组格式文件。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cookies.json"
        path.write_text(
            json.dumps([{"name": "unb", "value": "1"}, {"name": "_m_h5_tk", "value": "x"}]),
            encoding="utf-8",
        )
        sm = SessionManager(path)
        loaded = sm.load()
        assert loaded["unb"] == "1"
        assert sm.validate() is True


if __name__ == "__main__":
    test_save_and_load()
    test_validate_valid()
    test_validate_missing_key()
    test_load_not_exist()
    test_load_invalid_json()
    test_cookie_str()
    test_status_masked()
    test_status_not_exist()
    test_clear()
    test_nested_format()
    print("✅ test_session_manager: 全部通过")
