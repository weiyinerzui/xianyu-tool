"""登录态管理：cookie 加载 + 校验 + 持久化。

参考 goofish-cli core/session.py 的设计：
- 支持从 JSON 文件加载 cookie
- 校验关键字段（unb / _m_h5_tk）
- 提供 requests.Session 封装
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# 闲鱼登录态必需的 cookie 字段
REQUIRED_COOKIE_KEYS = ["unb", "_m_h5_tk"]
RECOMMENDED_COOKIE_KEYS = ["cookie2", "sgcookie", "unb", "cna", "isg", "_m_h5_tk"]


def _parse_cookie_header(s: str) -> dict[str, str]:
    """解析 Cookie 请求头字符串：'name=value; name2=value2'。"""
    result: dict[str, str] = {}
    for part in s.split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            if k.strip():
                result[k.strip()] = v.strip()
    if not result:
        raise SessionError("无法从字符串中解析出任何 cookie")
    return result


def normalize_cookies(data: Any) -> dict[str, str]:
    """把各种导出格式的 cookie 数据归一化为 dict[str, str]。

    支持格式：
    1. dict：{"name": "value", ...}
    2. DevTools/扩展导出的数组：[{"name": ..., "value": ..., (domain/path 等可选)}, ...]
    3. 包装对象：{"cookies": <上述任一格式>}
    4. Cookie 请求头字符串："name=value; name2=value2"
    5. 上述 JSON 的字符串形式（前端直接粘贴原文）
    """
    if isinstance(data, str):
        data = data.strip()
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return _parse_cookie_header(data)

    if isinstance(data, dict):
        if "cookies" in data and isinstance(data["cookies"], (dict, list)):
            return normalize_cookies(data["cookies"])
        return {
            str(k): str(v)
            for k, v in data.items()
            if isinstance(v, (str, int, float))
        }

    if isinstance(data, list):
        result: dict[str, str] = {}
        for item in data:
            if isinstance(item, dict) and "name" in item and "value" in item:
                result[str(item["name"])] = str(item["value"])
        if result:
            return result
        raise SessionError("数组格式需包含 name/value 字段的对象")

    raise SessionError("不支持的 cookie 格式")


class SessionError(Exception):
    """登录态异常。"""


class SessionManager:
    """登录态管理器。"""

    def __init__(self, cookies_path: str | Path | None = None) -> None:
        if cookies_path is None:
            cookies_path = Path(settings.cookies_path)
        self._path = Path(cookies_path)
        self._cookies: dict[str, str] = {}
        self._loaded = False

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, str]:
        """从文件加载 cookie。"""
        if not self._path.exists():
            raise SessionError(f"cookie 文件不存在：{self._path}")
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise SessionError(f"cookie 文件格式错误：{e}") from e

        # 兼容所有常见导出格式（dict / 数组 / 包装对象 / 头字符串）
        self._cookies = normalize_cookies(data)
        self._loaded = True
        return self._cookies

    def save(self, cookies: dict[str, str]) -> None:
        """保存 cookie 到文件。"""
        self._cookies = cookies
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            self._path.chmod(0o600)
        except OSError:
            pass
        self._loaded = True
        logger.info("cookies saved to %s", self._path)

    def validate(self) -> bool:
        """校验 cookie 是否包含必需字段。"""
        if not self._loaded:
            self.load()
        return all(k in self._cookies for k in REQUIRED_COOKIE_KEYS)

    def get_cookies(self) -> dict[str, str]:
        """获取 cookie dict。"""
        if not self._loaded:
            self.load()
        return self._cookies

    def get_cookie_str(self) -> str:
        """获取 cookie 字符串（用于 HTTP 头）。"""
        if not self._loaded:
            self.load()
        return "; ".join(f"{k}={v}" for k, v in self._cookies.items())

    def status(self) -> dict[str, Any]:
        """返回登录态状态摘要（脱敏）。"""
        if not self._loaded:
            try:
                self.load()
            except SessionError:
                return {"valid": False, "reason": "cookie 文件不存在"}

        valid = self.validate()
        has_recommended = [k for k in RECOMMENDED_COOKIE_KEYS if k in self._cookies]
        return {
            "valid": valid,
            "unb": self._mask(self._cookies.get("unb", "")),
            "tracknick": self._mask(self._cookies.get("tracknick", "")),
            "has_recommended_keys": has_recommended,
            "total_keys": len(self._cookies),
        }

    @staticmethod
    def _mask(value: str) -> str:
        """脱敏：只显示前2后2。"""
        if not value or len(value) <= 4:
            return "***"
        return f"{value[:2]}***{value[-2:]}"

    def clear(self) -> None:
        """清除登录态。"""
        self._cookies = {}
        self._loaded = False
        if self._path.exists():
            self._path.unlink()


# 模块级单例
_session: SessionManager | None = None


def get_session() -> SessionManager:
    global _session
    if _session is None:
        _session = SessionManager()
    return _session
