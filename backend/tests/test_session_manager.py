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
