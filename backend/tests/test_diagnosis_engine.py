"""曝光诊断引擎测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.diagnosis_engine import DiagnosisEngine, get_engine


def test_healthy_item():
    """健康商品应得高分。"""
    engine = get_engine()
    item = {
        "item_id": "123",
        "title": "罗技G502无线机械键盘 87键 黑色 学生党办公 95新现货",
        "price": 200,
        "market_avg_price": 220,
        "image_count": 5,
        "first_image_ratio": "1:1",
        "desc_length": 250,
        "category": "数码",
        "recommended_category": "数码",
        "account_health_score": 95,
    }
    report = engine.diagnose(item)
    assert report.overall_score >= 70
    assert report.risk_level == "healthy"
    assert len(report.matched_causes) == 0


def test_price_cut_title_change():
    """降价改标应命中 critical 归因。"""
    engine = get_engine()
    item = {
        "item_id": "456",
        "title": "某商品",
        "price_title_change_within_24h": True,
        "price_changed": True,
        "title_changed": True,
    }
    report = engine.diagnose(item)
    cause_ids = [c.id for c in report.matched_causes]
    assert "price_cut_title_change" in cause_ids
    cause = [c for c in report.matched_causes if c.id == "price_cut_title_change"][0]
    assert cause.severity == "critical"
    assert cause.confidence >= 0.9
    assert report.overall_score < 70


def test_wrong_category():
    """类目错放应命中。"""
    engine = get_engine()
    item = {
        "item_id": "789",
        "title": "手机壳",
        "category": "数码-手机",
        "recommended_category": "数码-手机配件",
        "category_mismatch": True,
    }
    report = engine.diagnose(item)
    cause_ids = [c.id for c in report.matched_causes]
    assert "wrong_category" in cause_ids


def test_poor_seo_title():
    """短标题应命中 SEO 归因。"""
    engine = get_engine()
    item = {
        "item_id": "101",
        "title": "耳机",  # 太短
    }
    report = engine.diagnose(item)
    cause_ids = [c.id for c in report.matched_causes]
    assert "poor_seo_title" in cause_ids


def test_image_non_compliant():
    """图片不合规应命中。"""
    engine = get_engine()
    item = {
        "item_id": "102",
        "title": "某商品标题",
        "image_count": 1,
        "first_image_ratio": "4:3",
        "has_watermark": True,
    }
    report = engine.diagnose(item)
    cause_ids = [c.id for c in report.matched_causes]
    assert "image_non_compliant" in cause_ids


def test_account_violation():
    """账号闲气值低应命中。"""
    engine = get_engine()
    item = {
        "item_id": "103",
        "title": "某商品",
        "account_health_score": 50,
        "has_violation_record": True,
    }
    report = engine.diagnose(item)
    cause_ids = [c.id for c in report.matched_causes]
    assert "account_violation_history" in cause_ids


def test_price_unreasonable():
    """价格偏离应命中。"""
    engine = get_engine()
    item = {
        "item_id": "104",
        "title": "某商品",
        "price": 50,
        "market_avg_price": 500,  # 10% 偏低
    }
    report = engine.diagnose(item)
    cause_ids = [c.id for c in report.matched_causes]
    assert "price_unreasonable" in cause_ids


def test_frequent_edit():
    """频繁编辑应命中。"""
    engine = get_engine()
    item = {
        "item_id": "105",
        "title": "某商品",
        "edit_count_within_1h": 5,
    }
    report = engine.diagnose(item)
    cause_ids = [c.id for c in report.matched_causes]
    assert "frequent_edit" in cause_ids


def test_new_account():
    """新号高频发布应命中。"""
    engine = get_engine()
    item = {
        "item_id": "106",
        "title": "某商品",
        "account_age_days": 3,
        "daily_publish_count": 8,
        "is_verified": False,
    }
    report = engine.diagnose(item)
    cause_ids = [c.id for c in report.matched_causes]
    assert "new_account_frequency" in cause_ids


def test_suggestions_generated():
    """命中归因应生成修复建议。"""
    engine = get_engine()
    item = {
        "item_id": "107",
        "title": "短",
        "price_title_change_within_24h": True,
    }
    report = engine.diagnose(item)
    assert len(report.suggestions) > 0


def test_anti_patterns_present():
    """报告应包含反模式警告。"""
    engine = get_engine()
    report = engine.diagnose({"title": "正常"})
    assert len(report.anti_pattern_warnings) > 0


def test_to_dict():
    """to_dict 应输出完整结构。"""
    engine = get_engine()
    report = engine.diagnose({"item_id": "x", "title": "测试", "price_title_change_within_24h": True})
    d = report.to_dict()
    assert "overall_score" in d
    assert "risk_level" in d
    assert "matched_causes" in d
    assert "factor_scores" in d
    assert "suggestions" in d


def test_causes_sorted_by_probability():
    """归因应按概率降序排列。"""
    engine = get_engine()
    item = {
        "title": "短",
        "price_title_change_within_24h": True,
        "category_mismatch": True,
        "image_count": 1,
        "first_image_ratio": "4:3",
    }
    report = engine.diagnose(item)
    probs = [c.probability for c in report.matched_causes]
    assert probs == sorted(probs, reverse=True)


if __name__ == "__main__":
    test_healthy_item()
    test_price_cut_title_change()
    test_wrong_category()
    test_poor_seo_title()
    test_image_non_compliant()
    test_account_violation()
    test_price_unreasonable()
    test_frequent_edit()
    test_new_account()
    test_suggestions_generated()
    test_anti_patterns_present()
    test_to_dict()
    test_causes_sorted_by_probability()
    print("✅ test_diagnosis_engine: 全部通过")
