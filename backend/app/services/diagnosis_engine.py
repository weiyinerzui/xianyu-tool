"""曝光诊断引擎。

基于规则库对商品/店铺进行曝光归因诊断。
规则来源：goofish-cli skills/goofish-shop-diagnosis 知识库转换。

诊断流程：
1. 接收商品元数据（标题/价格/类目/图片/发布时间/编辑历史等）
2. 按 traffic_drop_causes 清单逐条评估
3. 按 rank_factors 权重因子打分
4. 输出归因报告（嫌疑归因 + 修复建议 + 恢复周期）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class DiagnosisCause:
    """单条归因。"""
    id: str
    label: str
    probability: float       # 发生概率（0-1）
    severity: str            # critical / high / medium / low
    matched: bool            # 是否命中
    confidence: float        # 命中置信度（0-1）
    evidence: list[str]      # 命中证据
    cause: str
    fix: list[str]
    recovery: str = ""
    note: str = ""


@dataclass
class DiagnosisReport:
    """诊断报告。"""
    item_id: str = ""
    title: str = ""
    overall_score: float = 0.0     # 综合健康分（0-100）
    risk_level: str = "healthy"    # healthy / warning / danger
    matched_causes: list[DiagnosisCause] = field(default_factory=list)
    factor_scores: dict[str, float] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)
    anti_pattern_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "overall_score": round(self.overall_score, 1),
            "risk_level": self.risk_level,
            "matched_causes": [
                {
                    "id": c.id,
                    "label": c.label,
                    "probability": c.probability,
                    "severity": c.severity,
                    "matched": c.matched,
                    "confidence": round(c.confidence, 2),
                    "evidence": c.evidence,
                    "cause": c.cause,
                    "fix": c.fix,
                    "recovery": c.recovery,
                    "note": c.note,
                }
                for c in self.matched_causes
            ],
            "factor_scores": {k: round(v, 1) for k, v in self.factor_scores.items()},
            "suggestions": self.suggestions,
            "anti_pattern_warnings": self.anti_pattern_warnings,
        }


class DiagnosisEngine:
    """曝光诊断引擎。"""

    def __init__(self, yaml_path: str | Path | None = None) -> None:
        if yaml_path is None:
            yaml_path = Path(__file__).resolve().parent.parent / "data" / "diagnosis_rules.yaml"
        self._yaml_path = Path(yaml_path)
        self._rules: dict[str, Any] = {}
        self._loaded = False

    def load(self) -> None:
        with open(self._yaml_path, "r", encoding="utf-8") as f:
            self._rules = yaml.safe_load(f)
        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def diagnose(self, item: dict[str, Any]) -> DiagnosisReport:
        """对商品元数据进行诊断。

        item 字段（可选，缺失字段跳过对应检查）：
            item_id, title, price, category, recommended_category,
            image_count, first_image_ratio, has_watermark,
            desc_length, publish_hours, exposure_trend,
            price_changed, title_changed, price_title_change_within_24h,
            edit_count_within_1h, account_health_score,
            has_violation_record, account_age_days, daily_publish_count,
            is_verified, similar_listing_count, market_avg_price
        """
        self._ensure_loaded()

        report = DiagnosisReport(
            item_id=str(item.get("item_id", "")),
            title=item.get("title", ""),
        )

        causes_data = self._rules.get("traffic_drop_causes", [])
        for cause_def in causes_data:
            cause = self._evaluate_cause(cause_def, item)
            if cause.matched:
                report.matched_causes.append(cause)

        # 按概率排序
        report.matched_causes.sort(key=lambda c: c.probability, reverse=True)

        # 计算因子得分
        report.factor_scores = self._calc_factor_scores(item)

        # 综合健康分
        report.overall_score = self._calc_overall_score(report, item)

        # 风险等级
        if report.overall_score < 40:
            report.risk_level = "danger"
        elif report.overall_score < 70:
            report.risk_level = "warning"
        else:
            report.risk_level = "healthy"

        # 汇总建议
        report.suggestions = self._build_suggestions(report)
        report.anti_pattern_warnings = self._rules.get("anti_patterns", [])

        return report

    def _evaluate_cause(self, cause_def: dict[str, Any], item: dict[str, Any]) -> DiagnosisCause:
        """评估单条归因是否命中。"""
        cause = DiagnosisCause(
            id=cause_def["id"],
            label=cause_def["label"],
            probability=cause_def.get("probability", 0),
            severity=cause_def.get("severity", "medium"),
            matched=False,
            confidence=0.0,
            evidence=[],
            cause=cause_def.get("cause", ""),
            fix=cause_def.get("fix", []),
            note=cause_def.get("note", ""),
        )

        # 恢复周期
        for rp in self._rules.get("recovery_periods", []):
            if cause.label in rp.get("cause", "") or rp.get("cause", "") in cause.label:
                cause.recovery = rp.get("time", "")
                break

        # 根据 id 做具体判断
        cid = cause_def["id"]
        if cid == "price_cut_title_change":
            if item.get("price_title_change_within_24h"):
                cause.matched = True
                cause.confidence = 0.9
                cause.evidence.append("24小时内同时降价并改标题")
            elif item.get("price_changed") and item.get("title_changed"):
                cause.matched = True
                cause.confidence = 0.7
                cause.evidence.append("存在降价+改标题记录")

        elif cid == "wrong_category":
            if item.get("category_mismatch"):
                cause.matched = True
                cause.confidence = 0.85
                cause.evidence.append(
                    f"当前类目 {item.get('category','')} 与推荐类目 "
                    f"{item.get('recommended_category','')} 不一致"
                )
            elif item.get("category") and item.get("recommended_category"):
                if item["category"] != item["recommended_category"]:
                    cause.matched = True
                    cause.confidence = 0.8
                    cause.evidence.append("当前类目与AI推荐类目不一致")

        elif cid == "poor_seo_title":
            title = item.get("title", "")
            if not title:
                return cause
            issues = []
            title_len = len(title)
            if title_len < 18:
                issues.append(f"标题长度{title_len}字，低于建议的18字")
            if not item.get("has_core_keyword", True):
                issues.append("标题缺核心词")
            if not item.get("keyword_front_loaded", True) and title:
                issues.append("核心词未前置")
            if issues:
                cause.matched = True
                cause.confidence = 0.6
                cause.evidence.extend(issues)

        elif cid == "image_non_compliant":
            img_count = item.get("image_count", 0)
            ratio = item.get("first_image_ratio", "1:1")
            issues = []
            if img_count and img_count < 3:
                issues.append(f"图片仅{img_count}张，建议≥3张")
            if ratio and ratio != "1:1":
                issues.append(f"首图比例{ratio}，建议1:1")
            if item.get("has_watermark"):
                issues.append("图片含水印")
            if issues:
                cause.matched = True
                cause.confidence = 0.65
                cause.evidence.extend(issues)

        elif cid == "missed_initial_pool":
            hours = item.get("publish_hours", 0)
            trend = item.get("exposure_trend", "")
            if hours and hours > 24 and trend == "dropped_after_day1":
                cause.matched = True
                cause.confidence = 0.5
                cause.evidence.append("发布超24小时，曝光集中在第1天后掉零")

        elif cid == "account_violation_history":
            score = item.get("account_health_score", 100)
            if score and score < 80:
                cause.matched = True
                cause.confidence = 0.75
                cause.evidence.append(f"账号闲气值{score}，低于80")
            if item.get("has_violation_record"):
                cause.matched = True
                cause.confidence = max(cause.confidence, 0.8)
                cause.evidence.append("存在违规记录")

        elif cid == "price_unreasonable":
            price = item.get("price", 0)
            market = item.get("market_avg_price", 0)
            if price and market:
                ratio = price / market if market else 0
                if ratio < 0.7:
                    cause.matched = True
                    cause.confidence = 0.6
                    cause.evidence.append(f"定价为市场均价的{ratio:.0%}，疑似过低")
                elif ratio > 1.3:
                    cause.matched = True
                    cause.confidence = 0.5
                    cause.evidence.append(f"定价为市场均价的{ratio:.0%}，偏高")

        elif cid == "new_account_frequency":
            age = item.get("account_age_days", 999)
            daily = item.get("daily_publish_count", 0)
            verified = item.get("is_verified", True)
            if age and age < 7 and daily and daily > 3:
                cause.matched = True
                cause.confidence = 0.6
                cause.evidence.append(f"新号({age}天)单日发布{daily}件")
            if not verified and daily and daily > 3:
                cause.matched = True
                cause.confidence = max(cause.confidence, 0.7)
                cause.evidence.append("未实名账号单日发布超3件")

        elif cid == "frequent_edit":
            edit_count = item.get("edit_count_within_1h", 0)
            if edit_count and edit_count >= 3:
                cause.matched = True
                cause.confidence = 0.8
                cause.evidence.append(f"1小时内编辑{edit_count}次")

        elif cid == "duplicate_listing":
            similar = item.get("similar_listing_count", 0)
            if similar and similar >= 2:
                cause.matched = True
                cause.confidence = 0.6
                cause.evidence.append(f"存在{similar}件相似商品")

        return cause

    def _calc_factor_scores(self, item: dict[str, Any]) -> dict[str, float]:
        """计算各因子得分。"""
        scores: dict[str, float] = {}

        # 账号闲气值
        score = item.get("account_health_score", 100)
        if score is not None:
            if score < 60:
                scores["account_health"] = 0
            elif score < 80:
                scores["account_health"] = 40
            elif score < 95:
                scores["account_health"] = 80
            else:
                scores["account_health"] = 100

        # 标题质量
        title = item.get("title", "")
        if title:
            ts = 100
            if len(title) < 18:
                ts *= 0.6
            elif len(title) > 30:
                ts *= 0.7
            if not item.get("has_core_keyword", True):
                ts *= 0.5
            if not item.get("keyword_front_loaded", True):
                ts *= 0.7
            scores["title_quality"] = ts

        # 图片质量
        img_count = item.get("image_count")
        if img_count is not None:
            is_score = 100
            if img_count < 3:
                is_score *= 0.6
            if item.get("first_image_ratio", "1:1") != "1:1":
                is_score *= 0.7
            if item.get("has_watermark"):
                is_score *= 0.3
            scores["image_quality"] = is_score

        # 描述质量
        desc_len = item.get("desc_length")
        if desc_len is not None:
            if desc_len < 30:
                scores["desc_quality"] = 20
            elif desc_len < 100:
                scores["desc_quality"] = 60
            else:
                scores["desc_quality"] = 100

        # 类目匹配
        if item.get("category_mismatch"):
            scores["category_match"] = 30
        elif item.get("category"):
            scores["category_match"] = 100

        # 价格合理性
        price = item.get("price", 0)
        market = item.get("market_avg_price", 0)
        if price and market:
            ratio = price / market
            if 0.7 <= ratio <= 1.3:
                scores["price_reasonable"] = 100
            elif ratio < 0.7:
                scores["price_reasonable"] = 30
            else:
                scores["price_reasonable"] = 50

        return scores

    def _calc_overall_score(self, report: DiagnosisReport, item: dict[str, Any]) -> float:
        """计算综合健康分。"""
        if not report.factor_scores:
            return 50.0

        # 加权平均
        weights = {
            "account_health": 0.25,
            "title_quality": 0.20,
            "image_quality": 0.15,
            "desc_quality": 0.10,
            "category_match": 0.15,
            "price_reasonable": 0.15,
        }
        total_weight = 0
        weighted_sum = 0
        for factor, score in report.factor_scores.items():
            w = weights.get(factor, 0.1)
            weighted_sum += score * w
            total_weight += w

        base = weighted_sum / total_weight if total_weight else 50

        # 命中归因扣分
        for cause in report.matched_causes:
            if cause.severity == "critical":
                base -= 30 * cause.confidence
            elif cause.severity == "high":
                base -= 15 * cause.confidence
            elif cause.severity == "medium":
                base -= 8 * cause.confidence

        return max(0, min(100, base))

    def _build_suggestions(self, report: DiagnosisReport) -> list[str]:
        """汇总修复建议。"""
        suggestions: list[str] = []
        for cause in report.matched_causes:
            prefix = f"【{cause.label}】"
            for fix in cause.fix:
                suggestions.append(f"{prefix}{fix}")
        return suggestions


# 模块级单例
_engine: DiagnosisEngine | None = None


def get_engine() -> DiagnosisEngine:
    global _engine
    if _engine is None:
        _engine = DiagnosisEngine()
        _engine.load()
    return _engine
