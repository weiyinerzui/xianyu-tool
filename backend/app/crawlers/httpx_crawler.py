"""L1 采集器：httpx 直请求闲鱼搜索 mtop API（带签名）。

API 与签名流程参考（三个参考仓库一致确认）：
- goofish_api/spider/xianyu_sign.py：API 名 / data payload / md5 签名
- XianYuApis/static/goofish_js_version_2.js：generate_sign 算法
- goofish-cli core/mtop.py：params 结构 / 风控与令牌错误分类

要点：
- API：mtop.taobao.idlemtopsearch.pc.search（不是 awesome.post.search）
- sign = md5(token + "&" + t + "&" + appKey + "&" + data)
- token 取 _m_h5_tk cookie 下划线前半段；无 token 时先空签请求引导服务端
  通过 Set-Cookie 下发 _m_h5_tk，再重签重试一次
- 用户提供 cookies.json（含 _m_h5_tk）时直接带 cookie 签名请求
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import httpx

from app.crawlers.base import BaseCrawler, CrawledProduct, parse_search_api_json

logger = logging.getLogger(__name__)

SEARCH_API_NAME = "mtop.taobao.idlemtopsearch.pc.search"
SEARCH_API_URL = f"https://h5api.m.goofish.com/h5/{SEARCH_API_NAME}/1.0/"
APP_KEY = "34839810"
ROWS_PER_PAGE = 30

# 风控关键字（参考 goofish-cli core/mtop.py）
RISK_KEYWORDS = ("RGV587_ERROR", "FAIL_SYS_USER_VALIDATE", "哎哟喂", "/punish")
# 令牌层失效关键字（可通过重新引导 token 恢复）
TOKEN_FAIL_KEYWORDS = (
    "FAIL_SYS_TOKEN_EXOIRED",  # 服务端拼写就是 EXOIRED，不是笔误
    "FAIL_SYS_TOKEN_EMPTY",
    "FAIL_SYS_ILLEGAL_ACCESS",
)

# 模块级 token 缓存（进程内共享；_m_h5_tk 约 10 分钟 TTL，失效自动重引导）
_token_store: dict[str, str] = {"token": "", "raw": ""}


def get_h5_token() -> str:
    """当前缓存的 h5 token（_m_h5_tk 下划线前半段）。"""
    return _token_store["token"]


def set_h5_token(raw: str) -> bool:
    """从 _m_h5_tk 原始值提取并缓存 token。返回是否有效。"""
    token = (raw or "").split("_")[0].strip()
    if token:
        _token_store["token"] = token
        _token_store["raw"] = raw
        return True
    return False


def clear_h5_token() -> None:
    _token_store["token"] = ""
    _token_store["raw"] = ""


def generate_sign(t: str, token: str, data: str) -> str:
    """mtop h5 签名：md5(token + "&" + t + "&" + appKey + "&" + data)。"""
    msg = f"{token}&{t}&{APP_KEY}&{data}"
    return hashlib.md5(msg.encode("utf-8")).hexdigest()


def build_search_payload(keyword: str, page: int = 1) -> dict[str, Any]:
    """构造搜索 data payload（结构参考 goofish_api/spider/xianyu_sign.py）。"""
    return {
        "pageNumber": page,
        "keyword": keyword,
        "fromFilter": False,
        "rowsPerPage": ROWS_PER_PAGE,
        "sortValue": "",
        "sortField": "",
        "customDistance": "",
        "gps": "",
        "propValueStr": {},
        "customGps": "",
        "searchReqFromPage": "pcSearch",
        "extraFilterValue": "{}",
        "userPositionJson": "{}",
    }


def build_params(t: str, sign: str) -> dict[str, str]:
    """构造 mtop URL 参数。"""
    return {
        "jsv": "2.7.2",
        "appKey": APP_KEY,
        "t": t,
        "sign": sign,
        "v": "1.0",
        "type": "originaljson",
        "accountSite": "xianyu",
        "dataType": "json",
        "timeout": "20000",
        "api": SEARCH_API_NAME,
        "sessionOption": "AutoLoginOnly",
        "spm_cnt": "a21ybx.search.0.0",
    }


def _ret_str(data: dict) -> str:
    ret = data.get("ret") or []
    return " | ".join(ret) if isinstance(ret, list) else str(ret)


class HttpxCrawler(BaseCrawler):
    """L1: 直接 HTTP 请求闲鱼搜索 mtop 接口（自动 token 引导 + 签名）。"""

    async def search(self, keyword: str, category: str | None = None) -> list[CrawledProduct]:
        headers = self._headers()
        cookies = self._user_cookies()
        if cookies:
            set_h5_token(cookies.get("_m_h5_tk", ""))

        try:
            async with httpx.AsyncClient(
                timeout=20.0, follow_redirects=True, trust_env=False
            ) as client:
                if not get_h5_token():
                    await self._bootstrap_token(client, headers)

                products = await self._signed_search(client, keyword, category, headers, cookies)
                if products:
                    logger.info(
                        "HttpxCrawler: %d products for '%s'", len(products), keyword
                    )
                    return products

                # token 可能已过期：重新引导一次再试
                logger.info("HttpxCrawler: 首次无结果，刷新 token 重试 '%s'", keyword)
                await self._bootstrap_token(client, headers, force=True)
                products = await self._signed_search(client, keyword, category, headers, cookies)
                if products:
                    logger.info(
                        "HttpxCrawler(retry): %d products for '%s'", len(products), keyword
                    )
                    return products
        except httpx.HTTPError as e:
            logger.warning("HttpxCrawler 网络异常 '%s': %s", keyword, e)
            self._consecutive_failures += 1
            raise

        logger.warning("HttpxCrawler: no data for '%s'", keyword)
        return []

    async def _bootstrap_token(
        self, client: httpx.AsyncClient, headers: dict[str, str], force: bool = False
    ) -> None:
        """无 token（或强制）时发一次空签请求，从 Set-Cookie 拿 _m_h5_tk。

        服务端对空 token 请求返回 FAIL_SYS_TOKEN_EMPTY/EXOIRED 属预期，
        关键是响应会带上下发 _m_h5_tk cookie。
        """
        if get_h5_token() and not force:
            return
        t = str(int(time.time() * 1000))
        data_val = json.dumps(build_search_payload("token"), separators=(",", ":"))
        params = build_params(t, generate_sign(t, "", data_val))
        try:
            resp = await client.post(
                SEARCH_API_URL, params=params, headers=headers, data={"data": data_val}
            )
            self._absorb_token(resp)
            if get_h5_token():
                logger.info("HttpxCrawler: token 引导成功")
            else:
                logger.warning("HttpxCrawler: token 引导失败（响应未下发 _m_h5_tk）")
        except httpx.HTTPError as e:
            logger.warning("HttpxCrawler token 引导请求失败: %s", e)

    async def _signed_search(
        self,
        client: httpx.AsyncClient,
        keyword: str,
        category: str | None,
        headers: dict[str, str],
        cookies: dict[str, str] | None,
    ) -> list[CrawledProduct]:
        """带签名执行一次搜索请求。"""
        token = get_h5_token()
        if not token:
            logger.warning("HttpxCrawler: 无可用 token，跳过签名请求")
            return []

        t = str(int(time.time() * 1000))
        data_val = json.dumps(build_search_payload(keyword), separators=(",", ":"))
        params = build_params(t, generate_sign(t, token, data_val))

        resp = await client.post(
            SEARCH_API_URL,
            params=params,
            headers=headers,
            cookies=cookies or None,
            data={"data": data_val},
        )
        self._absorb_token(resp)
        if resp.status_code != 200:
            logger.warning("HttpxCrawler: HTTP %d", resp.status_code)
            return []

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            logger.warning("HttpxCrawler: 响应非 JSON")
            return []

        ret = _ret_str(data)
        if "SUCCESS" in ret:
            return parse_search_api_json(data, category or "")
        if any(k in ret for k in RISK_KEYWORDS):
            logger.warning("HttpxCrawler: 风控触发 [%s]", ret)
            return []
        if any(k in ret for k in TOKEN_FAIL_KEYWORDS):
            logger.warning("HttpxCrawler: 令牌失效 [%s]", ret)
            return []
        logger.warning("HttpxCrawler: 接口返回失败 [%s]", ret)
        return []

    def _absorb_token(self, resp: httpx.Response) -> None:
        """从响应 Set-Cookie 中提取 _m_h5_tk 更新 token 缓存。"""
        raw = resp.cookies.get("_m_h5_tk")
        if raw:
            set_h5_token(raw)

    def _user_cookies(self) -> dict[str, str] | None:
        """尝试加载用户导入的 cookies（含 _m_h5_tk 时 L1 命中率更高）。"""
        try:
            from app.services.session_manager import get_session

            session = get_session()
            if session.path.exists():
                cookies = session.get_cookies()
                return cookies or None
        except Exception as e:
            logger.debug("用户 cookies 加载失败: %s", e)
        return None

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.random_ua(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://www.goofish.com",
            "Referer": "https://www.goofish.com/",
            "sec-ch-ua": '"Chromium";v="131", "Not-A.Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        }
