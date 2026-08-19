"""L1 httpx 爬虫纯函数测试（不依赖网络）。

覆盖：mtop 签名算法、token 缓存、payload/params 构造、API 常量。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.crawlers.httpx_crawler import (
    APP_KEY,
    SEARCH_API_NAME,
    SEARCH_API_URL,
    build_params,
    build_search_payload,
    clear_h5_token,
    generate_sign,
    get_h5_token,
    set_h5_token,
)


def test_api_constants():
    """API 名称必须是 idlemtopsearch.pc.search（awesome.post.search 是错的）。"""
    assert SEARCH_API_NAME == "mtop.taobao.idlemtopsearch.pc.search"
    assert "idlemtopsearch.pc.search" in SEARCH_API_URL
    assert SEARCH_API_URL.startswith("https://h5api.m.goofish.com/h5/")
    assert APP_KEY == "34839810"


def test_generate_sign_format():
    """sign = md5(token & t & appKey & data)。"""
    token, t, data = "abc123", "1700000000000", '{"keyword":"测试"}'
    expected = hashlib.md5(
        f"{token}&{t}&{APP_KEY}&{data}".encode("utf-8")
    ).hexdigest()
    assert generate_sign(t, token, data) == expected
    assert len(generate_sign(t, token, data)) == 32


def test_generate_sign_empty_token():
    """空 token（引导阶段）也能签名，不抛异常。"""
    sign = generate_sign("1700000000000", "", "{}")
    assert len(sign) == 32


def test_generate_sign_sensitivity():
    """任一输入变化都会改变签名。"""
    base = generate_sign("123", "tok", "data")
    assert generate_sign("124", "tok", "data") != base
    assert generate_sign("123", "tok2", "data") != base
    assert generate_sign("123", "tok", "data2") != base


def test_token_store():
    """set_h5_token 从 _m_h5_tk 原始值提取下划线前半段。"""
    clear_h5_token()
    assert get_h5_token() == ""

    assert set_h5_token("abcdef123456_1700000000") is True
    assert get_h5_token() == "abcdef123456"

    # 无下划线时整个值就是 token
    assert set_h5_token("plainvalue") is True
    assert get_h5_token() == "plainvalue"

    # 空值返回 False 且不覆盖
    assert set_h5_token("") is False
    assert get_h5_token() == "plainvalue"

    clear_h5_token()
    assert get_h5_token() == ""


def test_build_search_payload():
    """payload 结构符合 goofish_api 参考实现。"""
    p = build_search_payload("考研资料", page=2)
    assert p["keyword"] == "考研资料"
    assert p["pageNumber"] == 2
    assert p["rowsPerPage"] == 30
    assert p["searchReqFromPage"] == "pcSearch"
    assert p["fromFilter"] is False
    # 默认第 1 页
    assert build_search_payload("x")["pageNumber"] == 1


def test_build_params():
    """mtop URL 参数完整且正确。"""
    params = build_params("1700000000000", "sig" * 10)
    assert params["api"] == SEARCH_API_NAME
    assert params["appKey"] == APP_KEY
    assert params["t"] == "1700000000000"
    assert params["sign"] == "sig" * 10
    assert params["v"] == "1.0"
    assert params["type"] == "originaljson"
    assert params["dataType"] == "json"
    assert params["accountSite"] == "xianyu"


if __name__ == "__main__":
    test_api_constants()
    test_generate_sign_format()
    test_generate_sign_empty_token()
    test_generate_sign_sensitivity()
    test_token_store()
    test_build_search_payload()
    test_build_params()
    print("✅ test_httpx_crawler: 全部通过")
