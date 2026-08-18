"""选品评分器。

基于 xianyu-tool/backend/app/services/scorer.py 的四维评分，
新增"竞争度指数"维度。

五维评分：
  1. 想要数增速 (want_velocity)    — 想要数增长速率
  2. 价格优势 (price_advantage)    — 相对类目均价的优势
  3. 互动率 (engagement_rate)      — 想要数/浏览数
  4. 新鲜度 (freshness)            — 发布时间越近分越高
  5. 竞争度 (competition)          — 同关键词在售数越少竞争越小（反向）
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

from app.config import settings


def calc_want_velocity(
    current_want: int, previous_want: Optional[int], hours: float
) -> float:
    """想要数增速：单位时间内的想要数增量。"""
    if previous_want is None or previous_want <= 0:
        return 0.0
    delta = current_want - previous_want
    if delta <= 0:
        return 0.0
    rate = delta / max(hours, 1.0)
    return min(rate * 10, 100.0)


def calc_price_advantage(price: float, category_avg_price: float) -> float:
    """价格优势：相对类目均价越低分越高（但不会无限高）。"""
    if price <= 0 or category_avg_price <= 0:
        return 0.0
    ratio = category_avg_price / price
    clamped = max(0.5, min(ratio, 2.0))
    return (clamped - 0.5) / 1.5 * 100.0


def calc_engagement_rate(want_count: int, view_count: int) -> float:
    """互动率：想要数/浏览数。"""
    if view_count <= 0:
        return 0.0
    rate = want_count / view_count
    return min(rate * 200, 100.0)


def calc_freshness(publish_time: Optional[datetime]) -> float:
    """新鲜度：发布越近分越高。"""
    if publish_time is None:
        return 50.0
    now = datetime.utcnow()
    age = now - publish_time
    if age <= timedelta(hours=24):
        return 100.0
    if age <= timedelta(days=3):
        return 80.0
    if age <= timedelta(days=7):
        return 50.0
    if age <= timedelta(days=30):
        return 25.0
    return 10.0


def calc_competition(total_listings: int, new_24h: int = 0) -> float:
    """竞争度指数（反向）：同关键词在售数越少，竞争越小，分越高。

    total_listings: 同关键词在售商品总数
    new_24h: 24小时内新增数（反映竞争加剧趋势）
    """
    if total_listings <= 0:
        return 100.0
    # 在售数越多竞争越激烈，分越低
    # 用对数压缩，避免数量级差异过大
    base = max(0.0, 100.0 - 20.0 * math.log10(total_listings + 1))
    # 24h新增多说明竞争在加剧，再扣分
    if new_24h > 0:
        base -= min(new_24h * 2, 30.0)
    return max(0.0, min(100.0, base))


def calc_hotness(want_count: int, publish_time: Optional[datetime] = None) -> float:
    """简单热度：想要数 / 发布天数。越新且想要数越多分越高。"""
    if publish_time is None:
        return float(want_count)
    days = max((datetime.utcnow() - publish_time).total_seconds() / 86400, 0.5)
    return want_count / days


def calc_days_ago(publish_time: Optional[datetime]) -> Optional[int]:
    """返回发布距今天数。"""
    if publish_time is None:
        return None
    return int((datetime.utcnow() - publish_time).total_seconds() / 86400)


def calculate_hot_score(
    current_want: int,
    previous_want: Optional[int],
    hours: float,
    price: float,
    category_avg_price: float,
    want_count: int,
    view_count: int,
    publish_time: Optional[datetime],
    total_listings: int = 0,
    new_24h: int = 0,
) -> dict[str, float]:
    """计算综合热度分（五维加权）。

    返回各维度分 + 总分。
    """
    wv = calc_want_velocity(current_want, previous_want, hours)
    pa = calc_price_advantage(price, category_avg_price)
    er = calc_engagement_rate(want_count, view_count)
    fr = calc_freshness(publish_time)
    cp = calc_competition(total_listings, new_24h)

    score = (
        wv * settings.weight_want_velocity
        + pa * settings.weight_price_advantage
        + er * settings.weight_engagement_rate
        + fr * settings.weight_freshness
        + cp * settings.weight_competition
    )

    return {
        "hot_score": round(score, 2),
        "want_velocity": round(wv, 2),
        "price_advantage": round(pa, 2),
        "engagement_rate": round(er, 2),
        "freshness": round(fr, 2),
        "competition": round(cp, 2),
    }


def calc_category_avg_price(prices: list[float]) -> float:
    """计算类目平均价格（去掉最高最低10%后取均值，抗离群值）。"""
    if not prices:
        return 0.0
    sorted_prices = sorted(prices)
    n = len(sorted_prices)
    if n <= 2:
        return sum(sorted_prices) / n
    trim = max(1, n // 10)
    trimmed = sorted_prices[trim : n - trim]
    return sum(trimmed) / len(trimmed) if trimmed else sum(sorted_prices) / n
