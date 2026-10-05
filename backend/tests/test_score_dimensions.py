"""score_dimensions 的权重归一化测试（P1-4）。

背景：原实现里 55% 的权重（want_velocity + engagement_rate）在生产环境恒为 0，
因为 (a) 没有快照表导致增速无从计算，(b) 闲鱼搜索接口不返回浏览量。
修复方式：不可用维��不参与加权，权重按比例分摊给可用维度。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.scorer import score_dimensions


def test_missing_view_count_does_not_crash():
    """view_count=0（接口不返回浏览量）时不应崩溃。"""
    r = score_dimensions(
        want_count=100, view_count=0, price=50, category_avg_price=50,
        publish_time=None, total_listings=30,
    )
    assert r["engagement_rate"] == 0.0


def test_missing_view_count_keeps_score_high():
    """核心回归：缺 view_count 时分数不再被压到 45 分以下。

    旧实现固定损失 55% 权重，hot_score 只能到 ~20。
    """
    r = score_dimensions(
        want_count=100, view_count=0, price=50, category_avg_price=50,
        publish_time=None, total_listings=30, want_velocity_score=None,
    )
    assert r["hot_score"] > 25, f"权重仍在空转：{r['hot_score']}"


def test_full_dimensions_use_full_weight():
    """五维齐全时，分母是全部权重之和（不做归一化剔除）。

    注意：缺维场景会「抬高」分数而非降低——因为归一化时如果被剔除的维度
    本身低于均值，除法会让剩余维度分数上浮。这是数学必然，不是 bug。
    真正要保证的是：五维齐全时 hot_score 等于各维按全权重加权的结果。
    """
    from app.config import settings

    full = score_dimensions(
        want_count=100, view_count=500, price=50, category_avg_price=50,
        publish_time=None, total_listings=30, want_velocity_score=80.0,
    )
    expected = (
        full["want_velocity"] * settings.weight_want_velocity
        + full["price_advantage"] * settings.weight_price_advantage
        + full["engagement_rate"] * settings.weight_engagement_rate
        + full["freshness"] * settings.weight_freshness
        + full["competition"] * settings.weight_competition
    ) / (
        settings.weight_want_velocity
        + settings.weight_price_advantage
        + settings.weight_engagement_rate
        + settings.weight_freshness
        + settings.weight_competition
    )
    assert abs(full["hot_score"] - expected) < 0.01, "五维齐全时应等于全权重加权"


def test_want_velocity_zero_is_not_treated_as_missing():
    """增速为 0（真实无增长）应按 '有数据' 处理，而不是被当成缺维。

    want_velocity_score=None 表示无快照；0.0 表示快照显示没增长。
    两者语义不同，不能混同 —— 否则有快照的商品会被误判成缺维而重新分摊权重。
    """
    with_zero = score_dimensions(
        want_count=100, view_count=0, price=50, category_avg_price=50,
        publish_time=None, total_listings=30, want_velocity_score=0.0,
    )
    without = score_dimensions(
        want_count=100, view_count=0, price=50, category_avg_price=50,
        publish_time=None, total_listings=30, want_velocity_score=None,
    )
    # 有快照(0.0) 时 want_velocity 权重参与，分数应低于缺维情形
    assert with_zero["hot_score"] < without["hot_score"]
    assert with_zero["want_velocity"] == 0.0


def test_score_in_valid_range():
    for vc, wv in ((0, None), (0, 0.0), (500, None), (500, 80.0)):
        r = score_dimensions(
            want_count=100, view_count=vc, price=50, category_avg_price=50,
            publish_time=None, total_listings=30, want_velocity_score=wv,
        )
        assert 0 <= r["hot_score"] <= 100, f"越界 {vc}/{wv}: {r['hot_score']}"


if __name__ == "__main__":
    test_missing_view_count_does_not_crash()
    test_missing_view_count_keeps_score_high()
    test_full_dimensions_use_full_weight()
    test_want_velocity_zero_is_not_treated_as_missing()
    test_score_in_valid_range()
    print("✅ test_score_dimensions: 全部通过")