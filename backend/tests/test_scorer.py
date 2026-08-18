"""选品评分器测试。"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.scorer import (
    calc_want_velocity,
    calc_price_advantage,
    calc_engagement_rate,
    calc_freshness,
    calc_competition,
    calc_hotness,
    calc_days_ago,
    calculate_hot_score,
    calc_category_avg_price,
)


def test_want_velocity():
    assert calc_want_velocity(100, 80, 2.0) > 0
    assert calc_want_velocity(80, 100, 2.0) == 0  # 下降
    assert calc_want_velocity(100, None, 2.0) == 0  # 无历史
    assert calc_want_velocity(100, 100, 2.0) == 0  # 无增长


def test_price_advantage():
    # 低于均价 = 优势
    assert calc_price_advantage(50, 100) > 50
    # 高于均价 = 劣势
    assert calc_price_advantage(200, 100) < 50
    # 等于均价（ratio=1.0 → (1.0-0.5)/1.5*100 ≈ 33.3）
    assert 30 < calc_price_advantage(100, 100) < 40
    # 边界
    assert calc_price_advantage(0, 100) == 0
    assert calc_price_advantage(100, 0) == 0


def test_engagement_rate():
    assert calc_engagement_rate(10, 100) > 0
    assert calc_engagement_rate(0, 100) == 0
    assert calc_engagement_rate(10, 0) == 0
    # 上限 100
    assert calc_engagement_rate(1000, 100) == 100


def test_freshness():
    now = datetime.utcnow()
    assert calc_freshness(now) == 100
    assert calc_freshness(now - timedelta(hours=12)) == 100
    assert calc_freshness(now - timedelta(days=2)) == 80
    assert calc_freshness(now - timedelta(days=5)) == 50
    assert calc_freshness(now - timedelta(days=10)) == 25
    assert calc_freshness(now - timedelta(days=60)) == 10
    assert calc_freshness(None) == 50


def test_competition():
    # 在售少 = 竞争小 = 高分
    assert calc_competition(1) > 80
    # 在售多 = 竞争大 = 低分
    assert calc_competition(1000) < calc_competition(10)
    # 24h 新增多 = 竞争加剧 = 扣分
    assert calc_competition(100, 10) < calc_competition(100, 0)
    # 0 在售
    assert calc_competition(0) == 100


def test_hotness():
    now = datetime.utcnow()
    assert calc_hotness(100, now) > calc_hotness(100, now - timedelta(days=10))
    assert calc_hotness(100, None) == 100


def test_days_ago():
    now = datetime.utcnow()
    assert calc_days_ago(now) == 0
    assert calc_days_ago(now - timedelta(days=5)) == 5
    assert calc_days_ago(None) is None


def test_calculate_hot_score():
    now = datetime.utcnow()
    result = calculate_hot_score(
        current_want=100,
        previous_want=80,
        hours=2.0,
        price=50,
        category_avg_price=100,
        want_count=100,
        view_count=500,
        publish_time=now,
        total_listings=50,
        new_24h=5,
    )
    assert "hot_score" in result
    assert "want_velocity" in result
    assert "price_advantage" in result
    assert "engagement_rate" in result
    assert "freshness" in result
    assert "competition" in result
    assert 0 <= result["hot_score"] <= 100
    # 新鲜度应该是满分（刚发布）
    assert result["freshness"] == 100


def test_category_avg_price():
    prices = [10, 20, 30, 40, 50, 100, 200]
    avg = calc_category_avg_price(prices)
    # 去掉最高最低10%后应该接近中间值
    assert 20 < avg < 60
    assert calc_category_avg_price([]) == 0
    assert calc_category_avg_price([100]) == 100


if __name__ == "__main__":
    test_want_velocity()
    test_price_advantage()
    test_engagement_rate()
    test_freshness()
    test_competition()
    test_hotness()
    test_days_ago()
    test_calculate_hot_score()
    test_category_avg_price()
    print("✅ test_scorer: 全部通过")
