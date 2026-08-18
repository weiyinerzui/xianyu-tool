"""违禁词检测引擎测试。"""
from __future__ import annotations

import sys
from pathlib import Path

# 让测试能直接 import app
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.banned_checker import BannedChecker, Severity, get_checker


def test_safe_text():
    """正常文本应通过检测。"""
    checker = get_checker()
    result = checker.check("考研英语真题复习资料 2026版 完整解析")
    assert result.passed is True
    assert result.risk_level == "safe"
    assert len(result.hits) == 0


def test_absolute_words():
    """绝对化用语应被 block。"""
    checker = get_checker()
    result = checker.check("全网最低价 最好的考研资料")
    assert result.passed is False
    assert result.risk_level == "danger"
    words = [h.word for h in result.hits]
    assert "全网最低" in words
    assert "最好" in words
    # 验证分类
    cats = {h.category for h in result.hits}
    assert "absolute" in cats


def test_external_contact():
    """外联词应被 block。"""
    checker = get_checker()
    result = checker.check("详情加微信详谈，私聊更方便")
    assert result.passed is False
    assert result.risk_level == "danger"
    words = [h.word for h in result.hits]
    assert "微信" in words


def test_virtual_goods_words():
    """虚拟商品专属违禁词应被 block。"""
    checker = get_checker()
    result = checker.check("Photoshop破解版 注册机 激活码")
    assert result.passed is False
    words = [h.word for h in result.hits]
    assert "破解版" in words
    assert "注册机" in words


def test_brand_warn():
    """品牌侵权词应为 warn 级别。"""
    checker = get_checker()
    result = checker.check("Nike运动鞋 正品")
    # Nike 是 warn
    assert result.risk_level in ("warn", "safe")
    words = [h.word for h in result.hits]
    assert "Nike" in words
    nike_hit = [h for h in result.hits if h.word == "Nike"][0]
    assert nike_hit.severity == Severity.WARN


def test_replacement_suggestion():
    """命中后应提供替换建议。"""
    checker = get_checker()
    result = checker.check("完美无瑕 全网最低")
    assert len(result.summary["suggestions"]) > 0
    # 至少有一条替换建议
    has_replacement = any("→" in s for s in result.summary["suggestions"])
    assert has_replacement


def test_regex_phone():
    """正则规则应检测手机号。"""
    checker = get_checker()
    result = checker.check("联系我 13812345678 详谈")
    regex_hits = [h for h in result.hits if h.source == "regex"]
    assert len(regex_hits) > 0
    assert regex_hits[0].word == "13812345678"


def test_position_accuracy():
    """命中位置应准确。"""
    checker = get_checker()
    text = "最好的资料"
    result = checker.check(text)
    hit = [h for h in result.hits if h.word == "最好"][0]
    assert text[hit.start:hit.end] == "最好"


def test_empty_text():
    """空文本应安全通过。"""
    checker = get_checker()
    result = checker.check("")
    assert result.passed is True
    assert result.risk_level == "safe"


def test_batch():
    """批量检测应正常工作。"""
    checker = get_checker()
    results = checker.check_batch(["正常文本", "全网最低", "加微信"])
    assert results[0].passed is True
    assert results[1].passed is False
    assert results[2].passed is False


def test_to_dict():
    """to_dict 应输出完整结构。"""
    checker = get_checker()
    result = checker.check("全网最低")
    d = result.to_dict()
    assert "text" in d
    assert "passed" in d
    assert "risk_level" in d
    assert "hits" in d
    assert "summary" in d
    assert d["block_count"] >= 1


if __name__ == "__main__":
    # 直接运行也能跑
    test_safe_text()
    test_absolute_words()
    test_external_contact()
    test_virtual_goods_words()
    test_brand_warn()
    test_replacement_suggestion()
    test_regex_phone()
    test_position_accuracy()
    test_empty_text()
    test_batch()
    test_to_dict()
    print("✅ test_banned_checker: 全部通过")
