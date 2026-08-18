"""采集层基础：数据结构 + 解析器 + 抽象基类。

解析器逻辑参考 ai-goofish-monitor/src/parsers.py 的 _parse_search_results_json，
适配到本项目同步数据结构。
"""
from __future__ import annotations

import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


def parse_publish_time(text: str) -> datetime | None:
    """解析中文时间表达：'3小时前发布' / '2天前' / '48小时内发布'。"""
    if not text:
        return None
    now = datetime.utcnow()
    text = text.strip()

    if "刚刚" in text:
        return now

    m = re.search(r"(\d+)\s*分钟前", text)
    if m:
        return now - timedelta(minutes=int(m.group(1)))

    m = re.search(r"(\d+)\s*小时(?:前|内)", text)
    if m:
        return now - timedelta(hours=int(m.group(1)))

    m = re.search(r"(\d+)\s*天前", text)
    if m:
        return now - timedelta(days=int(m.group(1)))

    m = re.search(r"(\d+)\s*天内发布", text)
    if m:
        return now - timedelta(days=int(m.group(1)) // 2)

    if "今天" in text:
        return now - timedelta(hours=12)
    if "昨天" in text:
        return now - timedelta(days=1)

    # 尝试标准日期格式 "2026-01-15 10:30"
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    return None


def safe_get(data: Any, *keys, default: Any = None) -> Any:
    """安全获取嵌套字典/列表值。"""
    for key in keys:
        try:
            if isinstance(data, (list, tuple)):
                data = data[int(key)]
            else:
                data = data[key]
        except (KeyError, TypeError, IndexError, ValueError):
            return default
    return data


@dataclass
class CrawledProduct:
    """采集到的商品数据。"""
    xianyu_id: str = ""
    title: str = ""
    price: float = 0.0
    original_price: float | None = None
    want_count: int = 0
    view_count: int = 0
    seller_name: str = ""
    seller_level: str = ""
    area: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    image_url: str = ""
    link: str = ""
    publish_time: datetime | None = None
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "xianyu_id": self.xianyu_id,
            "title": self.title,
            "price": self.price,
            "original_price": self.original_price,
            "want_count": self.want_count,
            "view_count": self.view_count,
            "seller_name": self.seller_name,
            "seller_level": self.seller_level,
            "area": self.area,
            "category": self.category,
            "tags": self.tags,
            "image_url": self.image_url,
            "link": self.link,
            "publish_time": self.publish_time.isoformat() if self.publish_time else None,
        }


def parse_price_str(price_str: str) -> float:
    """解析价格字符串：'¥99' / '1.2万' / '99.5' → float。"""
    if not price_str:
        return 0.0
    s = str(price_str).replace("¥", "").replace("当前价", "").replace(",", "").strip()
    try:
        if "万" in s:
            return float(s.replace("万", "")) * 10000
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def parse_search_api_json(json_data: dict, category: str = "") -> list[CrawledProduct]:
    """解析闲鱼搜索 API 的 JSON 响应。

    逻辑参考 ai-goofish-monitor/src/parsers.py 的 _parse_search_results_json。
    闲鱼搜索 API 返回结构：data.resultList[].data.item.main.exContent
    """
    products: list[CrawledProduct] = []

    items = safe_get(json_data, "data", "resultList", default=[])
    if not items:
        # 兼容其他结构
        items = safe_get(json_data, "data", "result", default=[])
    if not items:
        items = safe_get(json_data, "result", default=[])

    for item in items:
        try:
            main_data = safe_get(item, "data", "item", "main", "exContent", default={})
            click_params = safe_get(item, "data", "item", "main", "clickParam", "args", default={})

            title = safe_get(main_data, "title", default="未知标题")
            if not isinstance(title, str):
                title = str(title)

            # 价格
            price_parts = safe_get(main_data, "price", default=[])
            if isinstance(price_parts, list):
                price_str = "".join(
                    str(p.get("text", "")) for p in price_parts if isinstance(p, dict)
                ).replace("当前价", "").strip()
            else:
                price_str = str(price_parts)
            price = parse_price_str(price_str)

            original_price_str = safe_get(main_data, "oriPrice", default="")
            original_price = parse_price_str(str(original_price_str)) if original_price_str else None

            area = safe_get(main_data, "area", default="地区未知")
            seller = safe_get(main_data, "userNickName", default="匿名卖家")
            raw_link = safe_get(item, "data", "item", "main", "targetUrl", default="")
            image_url = safe_get(main_data, "picUrl", default="")
            item_id = safe_get(main_data, "itemId", default="")

            # 发布时间（毫秒时间戳）
            pub_time_ts = click_params.get("publishTime", "")
            publish_time: datetime | None = None
            if isinstance(pub_time_ts, str) and pub_time_ts.isdigit():
                publish_time = datetime.utcfromtimestamp(int(pub_time_ts) / 1000)
            elif isinstance(pub_time_ts, (int, float)):
                publish_time = datetime.utcfromtimestamp(pub_time_ts / 1000)

            # 想要数
            wants_raw = click_params.get("wantNum", 0)
            try:
                want_count = int(wants_raw) if wants_raw and str(wants_raw) != "NaN" else 0
            except (ValueError, TypeError):
                want_count = 0

            # 标签
            tags: list[str] = []
            if safe_get(click_params, "tag") == "freeship":
                tags.append("包邮")
            r1_tags = safe_get(main_data, "fishTags", "r1", "tagList", default=[])
            if isinstance(r1_tags, list):
                for tag_item in r1_tags:
                    content = safe_get(tag_item, "data", "content", default="")
                    if content and "验货宝" in str(content):
                        tags.append("验货宝")

            link = str(raw_link).replace("fleamarket://", "https://www.goofish.com/")

            # 跳过无 item_id 的畸形条目（safe_get 返回默认值而非抛异常）
            if not item_id or str(item_id) == "未知ID":
                continue

            products.append(CrawledProduct(
                xianyu_id=str(item_id),
                title=title,
                price=price,
                original_price=original_price if original_price else None,
                want_count=want_count,
                seller_name=str(seller),
                area=str(area),
                category=category,
                tags=tags,
                image_url=str(image_url),
                link=link,
                publish_time=publish_time,
                raw=item,
            ))
        except Exception:
            continue

    return products


class BaseCrawler(ABC):
    """采集器抽象基类。"""

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:139.0) Gecko/20100101 Firefox/139.0",
    ]

    def __init__(self) -> None:
        self._consecutive_failures = 0

    def random_ua(self) -> str:
        return random.choice(self.USER_AGENTS)

    def random_delay(self) -> float:
        from app.config import settings
        return random.uniform(
            settings.crawler_request_delay_min,
            settings.crawler_request_delay_max,
        )

    @abstractmethod
    async def search(self, keyword: str, category: str | None = None) -> list[CrawledProduct]:
        """搜索商品。"""
        ...
