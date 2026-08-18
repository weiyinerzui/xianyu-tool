"""标题优化器。

基于5段式公式（品牌+核心词+属性+场景+情感）对标题评分并给出优化建议。
规则来源：goofish-cli skills/goofish-publish-item/references/title-formula.md 转换。

与违禁词检测器联动：评分前先做违禁词扫描。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.services.banned_checker import BannedChecker, Severity, get_checker


@dataclass
class TitleScore:
    """标题评分结果。"""
    title: str
    total_score: float = 0.0          # 0-100
    length_score: float = 0.0
    structure_score: float = 0.0      # 5段式覆盖度
    keyword_position_score: float = 0.0
    banned_word_penalty: float = 0.0
    segments: dict[str, bool] = field(default_factory=dict)  # 各段是否覆盖
    length: int = 0
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    banned_hits: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "total_score": round(self.total_score, 1),
            "length_score": round(self.length_score, 1),
            "structure_score": round(self.structure_score, 1),
            "keyword_position_score": round(self.keyword_position_score, 1),
            "banned_word_penalty": round(self.banned_word_penalty, 1),
            "segments": self.segments,
            "length": self.length,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "banned_hits": self.banned_hits,
        }


class TitleAdvisor:
    """标题优化器。"""

    def __init__(
        self,
        rules_path: str | Path | None = None,
        checker: BannedChecker | None = None,
    ) -> None:
        if rules_path is None:
            rules_path = Path(__file__).resolve().parent.parent / "data" / "title_rules.yaml"
        self._rules_path = Path(rules_path)
        self._rules: dict[str, Any] = {}
        self._loaded = False
        self._checker = checker or get_checker()

    def load(self) -> None:
        with open(self._rules_path, "r", encoding="utf-8") as f:
            self._rules = yaml.safe_load(f)
        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def score(self, title: str, core_keyword: str = "") -> TitleScore:
        """对标题评分。

        Args:
            title: 商品标题
            core_keyword: 核心词（可选，用于判断前置和覆盖）
        """
        self._ensure_loaded()

        result = TitleScore(title=title, length=len(title))

        formula = self._rules.get("formula", {})
        segments_def = formula.get("segments", [])
        length_rules = self._rules.get("length", {})
        kw_pos_rules = self._rules.get("keyword_position", {})

        # 1. 长度评分
        min_len = length_rules.get("min", 18)
        max_len = length_rules.get("max", 28)
        max_with_brand = length_rules.get("max_with_brand", 30)
        effective_max = max_with_brand if result.segments.get("brand") else max_len

        if len(title) < min_len:
            result.length_score = 100 * length_rules.get("penalty_below_min", 0.6)
            result.issues.append(f"标题长度{len(title)}字，低于建议的{min_len}字")
        elif len(title) > effective_max:
            result.length_score = 100 * length_rules.get("penalty_above_max", 0.7)
            result.issues.append(f"标题长度{len(title)}字，超过建议的{effective_max}字")
        else:
            result.length_score = 100

        # 2. 结构评分（5段式覆盖度）
        total_weight = 0
        covered_weight = 0
        for seg in segments_def:
            sid = seg["id"]
            weight = seg.get("weight", 0.2)
            required = seg.get("required", False)
            total_weight += weight

            # 简单启发式判断各段是否覆盖
            covered = self._detect_segment(title, sid, core_keyword, seg)
            result.segments[sid] = covered

            if covered:
                covered_weight += weight
            elif required:
                result.issues.append(f"缺少必填段：{seg['label']}")

        result.structure_score = (covered_weight / total_weight * 100) if total_weight else 0

        # 3. 关键词位置评分
        if core_keyword and kw_pos_rules.get("core_keyword_front", True):
            pos = title.find(core_keyword)
            if pos >= 0 and pos <= len(title) / 3:
                result.keyword_position_score = 100
            elif pos >= 0:
                result.keyword_position_score = 100 * kw_pos_rules.get("front_penalty", 0.7)
                result.issues.append("核心词未前置（建议放在前1/3）")
            else:
                result.keyword_position_score = 50
                result.issues.append("标题中未找到核心词")
        else:
            result.keyword_position_score = 80  # 无核心词输入时给默认分

        # 4. 违禁词扣分
        check_result = self._checker.check(title)
        if check_result.hits:
            result.banned_hits = [
                {
                    "word": h.word,
                    "severity": h.severity.value,
                    "category": h.category_label,
                    "replacement": h.replacement,
                }
                for h in check_result.hits
            ]
            block_count = sum(1 for h in check_result.hits if h.severity == Severity.BLOCK)
            warn_count = sum(1 for h in check_result.hits if h.severity == Severity.WARN)
            result.banned_word_penalty = block_count * 30 + warn_count * 10
            for h in check_result.hits:
                if h.severity == Severity.BLOCK:
                    result.issues.append(f"含违禁词「{h.word}」（{h.category_label}，必须删除）")
                else:
                    result.issues.append(f"含敏感词「{h.word}」（{h.category_label}，建议修改）")

        # 5. 总分
        result.total_score = (
            result.length_score * 0.20
            + result.structure_score * 0.35
            + result.keyword_position_score * 0.20
            + 100 * 0.25  # 基础分
            - result.banned_word_penalty
        )
        result.total_score = max(0, min(100, result.total_score))

        # 6. 建议汇总
        result.suggestions = self._build_suggestions(result, segments_def)

        return result

    def _detect_segment(
        self, title: str, seg_id: str, core_keyword: str, seg_def: dict[str, Any]
    ) -> bool:
        """启发式判断标题是否覆盖某一段。"""
        examples = seg_def.get("examples", [])

        if seg_id == "core_keyword":
            if core_keyword:
                return core_keyword in title
            # 无核心词输入时，假设有
            return True

        if seg_id == "brand":
            # 检查是否含常见品牌词
            for ex in examples:
                if ex in title:
                    return True
            return False

        if seg_id == "attribute":
            # 检查是否含规格/型号特征（数字+单位、版本号等）
            import re
            if re.search(r"\d+\.?\d*[GBML年版本键寸gkK]|\d+版|v\d", title):
                return True
            for ex in examples:
                if ex in title:
                    return True
            return False

        if seg_id == "scene":
            scene_words = ["学生", "办公", "考研", "入门", "学习", "家用", "办公", "游戏",
                           "复习", "考试", "工作", "日常", "旅行", "送礼"]
            for w in scene_words:
                if w in title:
                    return True
            return False

        if seg_id == "emotion":
            emotion_words = ["新", "现货", "急出", "少见", "稀有", "限量", "收藏", "99新",
                             "95新", "9成新", "8成新", "全新"]
            for w in emotion_words:
                if w in title:
                    return True
            return False

        return False

    def _build_suggestions(self, result: TitleScore, segments_def: list[dict[str, Any]]) -> list[str]:
        suggestions: list[str] = []

        # 长度建议
        if result.length_score < 100:
            if len(result.title) < 18:
                suggestions.append(f"标题偏短（{result.length}字），建议补充属性/场景词到18-28字")
            else:
                suggestions.append(f"标题偏长（{result.length}字），建议精简到28字以内")

        # 缺段建议
        for seg in segments_def:
            sid = seg["id"]
            if not result.segments.get(sid) and seg.get("required"):
                suggestions.append(f"补充「{seg['label']}」：{seg.get('description','')}")
            elif not result.segments.get(sid) and not seg.get("required"):
                suggestions.append(f"可补充「{seg['label']}」提升覆盖度")

        # 违禁词替换建议
        for hit in result.banned_hits:
            if hit.get("replacement"):
                suggestions.append(f"「{hit['word']}」→ 替换为「{hit['replacement']}」")
            else:
                suggestions.append(f"「{hit['word']}」→ 直接删除")

        # 关键词位置建议
        if result.keyword_position_score < 100:
            suggestions.append("将核心词移到标题前1/3位置")

        return suggestions

    def generate(
        self,
        core_keyword: str,
        attribute: str = "",
        brand: str = "",
        scene: str = "",
        emotion: str = "",
    ) -> list[str]:
        """根据5段式生成候选标题。

        返回多个候选，按长度合规性排序。
        """
        self._ensure_loaded()
        length_rules = self._rules.get("length", {})
        min_len = length_rules.get("min", 18)
        max_len = length_rules.get("max", 28)

        parts = []
        if brand:
            parts.append(brand)
        parts.append(core_keyword)
        if attribute:
            parts.append(attribute)
        if scene:
            parts.append(scene)
        if emotion:
            parts.append(emotion)

        candidates: list[str] = []

        # 完整版
        full = "".join(parts)
        candidates.append(full)

        # 去掉可选段的变体
        if emotion:
            candidates.append("".join(parts[:-1]))
        if scene:
            without_scene = [p for p in parts if p != scene]
            candidates.append("".join(without_scene))
        if brand:
            without_brand = [p for p in parts if p != brand]
            candidates.append("".join(without_brand))

        # 去重 + 过滤违禁词 + 按长度合规排序
        seen: set[str] = set()
        unique: list[str] = []
        for c in candidates:
            if c and c not in seen:
                seen.add(c)
                # 违禁词检查
                check = self._checker.check(c)
                if check.risk_level == "danger":
                    continue
                unique.append(c)

        # 按与理想长度区间接近度排序
        def length_score(t: str) -> float:
            l = len(t)
            if min_len <= l <= max_len:
                return 0
            return min(abs(l - min_len), abs(l - max_len))

        unique.sort(key=length_score)
        return unique


# 模块级单例
_advisor: TitleAdvisor | None = None


def get_advisor() -> TitleAdvisor:
    global _advisor
    if _advisor is None:
        _advisor = TitleAdvisor()
        _advisor.load()
    return _advisor
