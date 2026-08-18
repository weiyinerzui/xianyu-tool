"""采集层解析器测试（不依赖网络）。"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.crawlers.base import (
    CrawledProduct,
    parse_search_api_json,
    parse_price_str,
    parse_publish_time,
    safe_get,
)


def _mock_search_response() -> dict:
    """构造一个模拟的闲鱼搜索 API 响应（结构参考 ai-goofish-monitor）。"""
    return {
        "data": {
            "resultList": [
                {
                    "data": {
                        "item": {
                            "main": {
                                "exContent": {
                                    "title": "考研英语真题资料 2026版",
                                    "price": [{"text": "¥"}, {"text": "29.9"}],
                                    "oriPrice": "¥49.9",
                                    "area": "浙江杭州",
                                    "userNickName": "学霸店铺",
                                    "picUrl": "https://img.example.com/1.jpg",
                                    "itemId": "123456789",
                                    "fishTags": {
                                        "r1": {
                                            "tagList": [
                                                {"data": {"content": "验货宝"}}
                                            ]
                                        }
                                    },
                                },
                                "clickParam": {
                                    "args": {
                                        "publishTime": "1700000000000",
                                        "wantNum": "35",
                                        "tag": "freeship",
                                    }
                                },
                                "targetUrl": "fleamarket://item?id=123456789",
                            }
                        }
                    }
                },
                {
                    "data": {
                        "item": {
                            "main": {
                                "exContent": {
                                    "title": "Python教程入门到精通",
                                    "price": [{"text": "当前价"}, {"text": "¥"}, {"text": "15"}],
                                    "area": "广东深圳",
                                    "userNickName": "码农小店",
                                    "picUrl": "",
                                    "itemId": "987654321",
                                },
                                "clickParam": {
                                    "args": {
                                        "publishTime": "1700100000000",
                                        "wantNum": "12",
                                    }
                                },
                                "targetUrl": "https://www.goofish.com/item?id=987654321",
                            }
                        }
                    }
                },
            ]
        }
    }


def test_parse_price_str():
    assert parse_price_str("¥99") == 99.0
    assert parse_price_str("1.2万") == 12000.0
    assert parse_price_str("29.9") == 29.9
    assert parse_price_str("") == 0.0
    assert parse_price_str("当前价¥49.9") == 49.9


def test_parse_publish_time():
    from datetime import timedelta
    now = datetime.utcnow()
    assert parse_publish_time("刚刚发布") is not None
    t = parse_publish_time("3小时前发布")
    assert t is not None
    assert abs((now - t).total_seconds() - 3 * 3600) < 60
    t = parse_publish_time("2天前")
    assert t is not None
    assert abs((now - t).days - 2) <= 1
    assert parse_publish_time("") is None
    assert parse_publish_time("未知时间") is None


def test_safe_get():
    data = {"a": {"b": {"c": 42}}}
    assert safe_get(data, "a", "b", "c") == 42
    assert safe_get(data, "a", "x", default="def") == "def"
    assert safe_get(data, "x", "y", default=None) is None
    # 列表索引
    assert safe_get([10, 20, 30], 1) == 20
    assert safe_get([10, 20], 5, default="oob") == "oob"


def test_parse_search_api_json_basic():
    """解析模拟搜索响应。"""
    products = parse_search_api_json(_mock_search_response(), "学习资料")
    assert len(products) == 2

    p1 = products[0]
    assert p1.xianyu_id == "123456789"
    assert p1.title == "考研英语真题资料 2026版"
    assert p1.price == 29.9
    assert p1.original_price == 49.9
    assert p1.want_count == 35
    assert p1.seller_name == "学霸店铺"
    assert p1.area == "浙江杭州"
    assert p1.category == "学习资料"
    assert p1.publish_time is not None
    assert "包邮" in p1.tags
    assert "验货宝" in p1.tags
    assert "fleamarket://" not in p1.link
    assert "goofish.com" in p1.link


def test_parse_search_api_json_second_item():
    """第二个商品字段正确。"""
    products = parse_search_api_json(_mock_search_response(), "学习资料")
    p2 = products[1]
    assert p2.xianyu_id == "987654321"
    assert p2.title == "Python教程入门到精通"
    assert p2.price == 15.0
    assert p2.want_count == 12
    assert p2.original_price is None
    assert p2.tags == []  # 无标签


def test_parse_empty_response():
    """空响应应返回空列表。"""
    assert parse_search_api_json({}, "") == []
    assert parse_search_api_json({"data": {}}, "") == []
    assert parse_search_api_json({"data": {"resultList": []}}, "") == []


def test_parse_malformed_item_skipped():
    """畸形条目应被跳过而非崩溃。"""
    data = {
        "data": {
            "resultList": [
                {"broken": "item"},  # 缺字段
                {
                    "data": {
                        "item": {
                            "main": {
                                "exContent": {"title": "正常", "itemId": "1"},
                                "clickParam": {"args": {}},
                                "targetUrl": "",
                            }
                        }
                    }
                },
            ]
        }
    }
    products = parse_search_api_json(data, "")
    # 畸形条目被跳过，正常条目保留
    assert len(products) == 1
    assert products[0].title == "正常"


def test_crawled_product_to_dict():
    """to_dict 序列化正确。"""
    cp = CrawledProduct(
        xianyu_id="123",
        title="测试",
        price=9.9,
        want_count=5,
        tags=["包邮"],
    )
    d = cp.to_dict()
    assert d["xianyu_id"] == "123"
    assert d["price"] == 9.9
    assert d["want_count"] == 5
    assert d["tags"] == ["包邮"]
    assert d["publish_time"] is None


if __name__ == "__main__":
    test_parse_price_str()
    test_parse_publish_time()
    test_safe_get()
    test_parse_search_api_json_basic()
    test_parse_search_api_json_second_item()
    test_parse_empty_response()
    test_parse_malformed_item_skipped()
    test_crawled_product_to_dict()
    print("✅ test_crawler_parser: 全部通过")
