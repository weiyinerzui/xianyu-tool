"""标题优化器测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.title_advisor import TitleAdvisor, get_advisor


def test_good_title():
    """合规且结构完整的标题应得高分。"""
    advisor = get_advisor()
    title = "罗技G502无线机械键盘 87键 黑色 学生党办公 95新现货"
    result = advisor.score(title, core_keyword="机械键盘")
    assert result.total_score >= 60
    assert result.length >= 18
    assert result.segments.get("core_keyword") is True


def test_short_title():
    """短标题应扣分。"""
    advisor = get_advisor()
    result = advisor.score("耳机", core_keyword="耳机")
    assert result.length_score < 100
    assert "低于建议的" in result.issues[0] or any("低于" in i for i in result.issues)


def test_banned_word_in_title():
    """含违禁词的标题应扣分并提示。"""
    advisor = get_advisor()
    result = advisor.score("全网最低最好的考研资料包过", core_keyword="考研资料")
    assert result.banned_word_penalty > 0
    assert len(result.banned_hits) > 0
    assert result.total_score < 80


def test_core_keyword_front():
    """核心词前置应得满分。"""
    advisor = get_advisor()
    title = "考研资料2026版英语真题完整解析 学生党复习 现货"
    result = advisor.score(title, core_keyword="考研资料")
    assert result.keyword_position_score == 100


def test_core_keyword_not_front():
    """核心词未前置应扣分。"""
    advisor = get_advisor()
    # 关键词放在标题后半段，确保超过 1/3 位置
    title = "学生党考研复习专用完整版真题解析 考研资料"
    result = advisor.score(title, core_keyword="考研资料")
    assert result.keyword_position_score < 100


def test_generate_candidates():
    """生成候选标题应返回多个合规选项。"""
    advisor = get_advisor()
    candidates = advisor.generate(
        core_keyword="考研英语真题资料",
        attribute="2026版完整解析",
        brand="",
        scene="学生党复习专用",
        emotion="现货急出",
    )
    assert len(candidates) > 0
    # 至少有一个在合理长度区间
    has_valid_length = any(18 <= len(c) <= 30 for c in candidates)
    assert has_valid_length


def test_generate_filters_banned():
    """生成的候选不应含违禁词。"""
    advisor = get_advisor()
    candidates = advisor.generate(
        core_keyword="破解版软件",  # 含违禁词
        attribute="",
    )
    # 应被过滤掉或返回空
    for c in candidates:
        check = advisor._checker.check(c)
        assert check.risk_level != "danger"


def test_segment_detection():
    """5段式覆盖检测应正确。"""
    advisor = get_advisor()
    title = "罗技机械键盘 87键 学生党 95新"
    result = advisor.score(title, core_keyword="机械键盘")
    assert result.segments.get("brand") is True
    assert result.segments.get("core_keyword") is True
    assert result.segments.get("scene") is True
    assert result.segments.get("emotion") is True


def test_suggestions_generated():
    """应生成优化建议。"""
    advisor = get_advisor()
    result = advisor.score("耳机", core_keyword="耳机")
    assert len(result.suggestions) > 0


def test_to_dict():
    """to_dict 应输出完整结构。"""
    advisor = get_advisor()
    result = advisor.score("测试标题", core_keyword="测试")
    d = result.to_dict()
    assert "total_score" in d
    assert "length_score" in d
    assert "structure_score" in d
    assert "segments" in d
    assert "suggestions" in d


if __name__ == "__main__":
    test_good_title()
    test_short_title()
    test_banned_word_in_title()
    test_core_keyword_front()
    test_core_keyword_not_front()
    test_generate_candidates()
    test_generate_filters_banned()
    test_segment_detection()
    test_suggestions_generated()
    test_to_dict()
    print("✅ test_title_advisor: 全部通过")
