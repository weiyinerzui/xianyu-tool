"""违禁词检测引擎。

基于 AC 自动机（Aho-Corasick）实现多模式匹配，支持：
- 精确词匹配（6 类违禁词 + 虚拟商品专属词）
- 正则规则匹配（手机号、QQ 号等变体）
- 分级输出（block / warn / info）
- 替换建议
- 整体风险评估

词库来源：goofish-cli skills/goofish-risk-guard 知识库转换。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class Severity(str, Enum):
    BLOCK = "block"   # 必须删除/替换，否则拒绝发布
    WARN = "warn"     # 建议修改，可能触发降权
    INFO = "info"     # 提示性，需结合上下文判断


@dataclass
class Hit:
    """单条命中记录。"""
    category: str          # 词库分类（absolute/external_contact/...）
    category_label: str    # 中文标签
    word: str              # 命中的词
    severity: Severity
    start: int             # 起始位置
    end: int               # 结束位置
    replacement: str = ""  # 推荐替换词
    note: str = ""         # 说明
    source: str = "word"   # word | regex


@dataclass
class CheckResult:
    """检测结果。"""
    text: str
    hits: list[Hit] = field(default_factory=list)
    passed: bool = True
    risk_level: str = "safe"  # safe | warn | danger
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "passed": self.passed,
            "risk_level": self.risk_level,
            "hit_count": len(self.hits),
            "block_count": sum(1 for h in self.hits if h.severity == Severity.BLOCK),
            "warn_count": sum(1 for h in self.hits if h.severity == Severity.WARN),
            "info_count": sum(1 for h in self.hits if h.severity == Severity.INFO),
            "hits": [
                {
                    "category": h.category,
                    "category_label": h.category_label,
                    "word": h.word,
                    "severity": h.severity.value,
                    "position": [h.start, h.end],
                    "replacement": h.replacement,
                    "note": h.note,
                    "source": h.source,
                }
                for h in self.hits
            ],
            "summary": self.summary,
        }


# 分类中文标签
CATEGORY_LABELS = {
    "absolute": "绝对化用语",
    "external_contact": "外联/诱导线下",
    "brand_infringement": "品牌侵权",
    "medical_exaggeration": "医疗/保健夸大",
    "sensitive": "擦边/敏感",
    "fake_data": "虚假数据",
    "virtual_goods": "虚拟商品专属",
}


class _ACNode:
    """AC 自动机节点。"""

    __slots__ = ("children", "fail", "output", "word", "category", "severity",
                 "replacement", "note")

    def __init__(self) -> None:
        self.children: dict[str, _ACNode] = {}
        self.fail: _ACNode | None = None
        self.output: list[int] = []  # 存放该节点对应的词条索引
        # 词条信息（output 为空时无意义）
        self.word: str = ""
        self.category: str = ""
        self.severity: Severity = Severity.WARN
        self.replacement: str = ""
        self.note: str = ""


class AhoCorasick:
    """简易 AC 自动机实现。

    用字典存子节点，构建 fail 指针（BFS）。匹配时沿 fail 链收集所有命中。
    对中文按字符处理（每个汉字/字符作为一个转移边）。
    """

    def __init__(self) -> None:
        self._root = _ACNode()
        self._entries: list[dict[str, Any]] = []  # 所有词条元信息
        self._built = False

    def add_pattern(
        self,
        word: str,
        category: str,
        severity: Severity,
        replacement: str = "",
        note: str = "",
    ) -> None:
        if not word:
            return
        node = self._root
        for ch in word:
            if ch not in node.children:
                node.children[ch] = _ACNode()
            node = node.children[ch]
        idx = len(self._entries)
        node.output.append(idx)
        node.word = word
        node.category = category
        node.severity = severity
        node.replacement = replacement
        node.note = note
        self._entries.append({
            "word": word, "category": category, "severity": severity,
            "replacement": replacement, "note": note,
        })
        self._built = False

    def build(self) -> None:
        """构建 fail 指针。"""
        from collections import deque

        queue: deque[_ACNode] = deque()
        # 根的直接子节点 fail 指向根
        for child in self._root.children.values():
            child.fail = self._root
            queue.append(child)

        while queue:
            current = queue.popleft()
            for ch, child in current.children.items():
                # 求 child.fail
                fail = current.fail
                while fail is not None and ch not in fail.children:
                    fail = fail.fail
                child.fail = fail.children[ch] if fail else self._root
                if child.fail is child:
                    child.fail = self._root
                # 合并 output
                child.output.extend(child.fail.output)
                queue.append(child)

        self._built = True

    def search(self, text: str) -> list[dict[str, Any]]:
        """在 text 中搜索所有命中。返回命中列表（含位置）。"""
        if not self._built:
            self.build()

        results: list[dict[str, Any]] = []
        node = self._root

        for i, ch in enumerate(text):
            while node is not self._root and ch not in node.children:
                node = node.fail  # type: ignore[assignment]
            if ch in node.children:
                node = node.children[ch]
            # 收集当前节点所有 output
            for idx in node.output:
                entry = self._entries[idx]
                word = entry["word"]
                start = i - len(word) + 1
                results.append({
                    "word": word,
                    "category": entry["category"],
                    "severity": entry["severity"],
                    "replacement": entry["replacement"],
                    "note": entry["note"],
                    "start": start,
                    "end": i + 1,
                })

        return results


class BannedChecker:
    """违禁词检测器。

    加载 YAML 词库，构建 AC 自动机 + 正则规则，提供 check() 方法。
    """

    def __init__(self, yaml_path: str | Path | None = None) -> None:
        if yaml_path is None:
            yaml_path = Path(__file__).resolve().parent.parent / "data" / "banned_words.yaml"
        self._yaml_path = Path(yaml_path)
        self._ac = AhoCorasick()
        self._regex_rules: list[dict[str, Any]] = []
        self._loaded = False

    def load(self) -> None:
        """加载词库并构建 AC 自动机。"""
        with open(self._yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        for category, label in CATEGORY_LABELS.items():
            cat_data = data.get(category)
            if not cat_data:
                continue
            severity = Severity(cat_data.get("severity", "warn"))
            for entry in cat_data.get("words", []):
                word = entry.get("word", "").strip()
                if not word:
                    continue
                self._ac.add_pattern(
                    word=word,
                    category=category,
                    severity=severity,
                    replacement=entry.get("replacement", ""),
                    note=entry.get("note", ""),
                )

        self._regex_rules = data.get("regex_rules", [])
        self._ac.build()
        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def check(self, text: str) -> CheckResult:
        """检测文本，返回 CheckResult。"""
        self._ensure_loaded()

        if not text:
            return CheckResult(text=text)

        hits: list[Hit] = []

        # 1. AC 自动机精确匹配
        for match in self._ac.search(text):
            hits.append(Hit(
                category=match["category"],
                category_label=CATEGORY_LABELS.get(match["category"], match["category"]),
                word=match["word"],
                severity=match["severity"],
                start=match["start"],
                end=match["end"],
                replacement=match["replacement"],
                note=match["note"],
                source="word",
            ))

        # 2. 正则规则匹配
        for rule in self._regex_rules:
            pattern = rule.get("pattern", "")
            if not pattern:
                continue
            severity = Severity(rule.get("severity", "info"))
            for m in re.finditer(pattern, text):
                hits.append(Hit(
                    category="regex",
                    category_label=rule.get("name", "正则规则"),
                    word=m.group(),
                    severity=severity,
                    start=m.start(),
                    end=m.end(),
                    replacement=rule.get("replacement", ""),
                    note=rule.get("note", ""),
                    source="regex",
                ))

        # 去重（同一位置同一词只保留一条）
        seen: set[tuple[int, int, str]] = set()
        deduped: list[Hit] = []
        for h in hits:
            key = (h.start, h.end, h.word)
            if key not in seen:
                seen.add(key)
                deduped.append(h)
        hits = sorted(deduped, key=lambda h: h.start)

        # 评估风险等级
        has_block = any(h.severity == Severity.BLOCK for h in hits)
        has_warn = any(h.severity == Severity.WARN for h in hits)
        if has_block:
            risk_level = "danger"
            passed = False
        elif has_warn:
            risk_level = "warn"
            passed = True
        else:
            risk_level = "safe"
            passed = True

        # 汇总
        summary: dict[str, Any] = {
            "categories": {},
            "suggestions": [],
        }
        for h in hits:
            cat = h.category_label
            summary["categories"][cat] = summary["categories"].get(cat, 0) + 1
            if h.replacement:
                summary["suggestions"].append(
                    f"「{h.word}」→ 建议替换为「{h.replacement}」"
                )
            elif h.severity == Severity.BLOCK:
                summary["suggestions"].append(f"「{h.word}」→ 建议直接删除")

        return CheckResult(
            text=text,
            hits=hits,
            passed=passed,
            risk_level=risk_level,
            summary=summary,
        )

    def check_batch(self, texts: list[str]) -> list[CheckResult]:
        """批量检测。"""
        return [self.check(t) for t in texts]


# 模块级单例（懒加载）
_checker: BannedChecker | None = None


def get_checker() -> BannedChecker:
    global _checker
    if _checker is None:
        _checker = BannedChecker()
        _checker.load()
    return _checker
