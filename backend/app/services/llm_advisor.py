"""LLM 接口抽象：标题/文案优化、违禁词智能判断。

支持 OpenAI 兼容接口（通义/DeepSeek/OpenAI 等）。
未配置 API key 时降级为规则引擎（title_advisor + banned_checker）。
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class LLMAdvisor:
    """LLM 顾问：标题优化、文案生成、违禁词语义判断。

    优先使用 LLM（如果配置了 API key），否则降级为规则引擎。
    """

    def __init__(self) -> None:
        self._api_key = os.getenv("LLM_API_KEY", "")
        self._base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
        self._model = os.getenv("LLM_MODEL", "deepseek-chat")
        self._enabled = bool(self._api_key)

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """调用 OpenAI 兼容接口。"""
        import httpx

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 1000,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def optimize_title(
        self, title: str, core_keyword: str = "", category: str = ""
    ) -> dict[str, Any]:
        """优化标题：生成 3-5 个合规且高曝光的候选标题。

        LLM 不可用时降级为 title_advisor.generate()。
        """
        from app.services.banned_checker import get_checker
        from app.services.title_advisor import get_advisor

        if not self._enabled:
            # 降级：规则引擎
            advisor = get_advisor()
            candidates = advisor.generate(
                core_keyword=core_keyword or title,
                attribute="",
                brand="",
                scene="",
                emotion="",
            )
            return {
                "source": "rule_engine",
                "original": title,
                "candidates": candidates[:5],
            }

        system_prompt = (
            "你是闲鱼商品标题优化专家。根据输入的标题和核心词，生成 5 个优化标题。"
            "要求：1) 长度18-28字 2) 核心词前置 3) 不含违禁词（最/第一/全网最低/微信等）"
            "4) 覆盖品牌+核心词+属性+场景+情感 5) 每行一个标题，不要编号"
        )
        user_prompt = f"原标题：{title}\n核心词：{core_keyword}\n类目：{category}"

        try:
            content = await self._call_llm(system_prompt, user_prompt)
            candidates = [c.strip() for c in content.strip().split("\n") if c.strip()]

            # 过滤违禁词
            checker = get_checker()
            safe_candidates = [
                c for c in candidates
                if checker.check(c).risk_level != "danger"
            ]

            return {
                "source": "llm",
                "original": title,
                "candidates": safe_candidates[:5],
            }
        except Exception as e:
            logger.warning("LLM 调用失败，降级规则引擎: %s", e)
            advisor = get_advisor()
            candidates = advisor.generate(core_keyword=core_keyword or title)
            return {
                "source": "rule_engine_fallback",
                "original": title,
                "candidates": candidates[:5],
                "error": str(e),
            }

    async def generate_description(
        self, title: str, category: str = "", key_features: str = ""
    ) -> dict[str, Any]:
        """生成商品描述（200-400字，结构完整）。"""
        if not self._enabled:
            return {
                "source": "rule_engine",
                "description": self._rule_description(title, category, key_features),
            }

        system_prompt = (
            "你是闲鱼商品描述撰写专家。根据标题和特征生成 200-400 字的商品描述。"
            "结构：商品信息→成色/状态→使用场景→发货说明→砍价政策。"
            "不含违禁词，不包含联系方式，不使用绝对化用语。"
        )
        user_prompt = f"标题：{title}\n类目：{category}\n特征：{key_features}"

        try:
            content = await self._call_llm(system_prompt, user_prompt)
            # 违禁词检查
            from app.services.banned_checker import get_checker
            check = get_checker().check(content)
            return {
                "source": "llm",
                "description": content,
                "banned_check": check.to_dict(),
            }
        except Exception as e:
            logger.warning("LLM 调用失败: %s", e)
            return {
                "source": "rule_engine_fallback",
                "description": self._rule_description(title, category, key_features),
                "error": str(e),
            }

    @staticmethod
    def _rule_description(title: str, category: str, features: str) -> str:
        """规则引擎兜底描述。"""
        parts = [
            f"【商品】{title}",
            f"【类目】{category or '通用'}",
            f"【特征】{features or '详见图片'}",
            "【成色】详见实物拍摄，有疑问请私信",
            "【发货】拍下后及时发送，支持闲鱼担保交易",
            "【说明】如有问题请在闲鱼内沟通，看到秒回",
        ]
        return "\n".join(parts)


# 模块级单例
_llm: LLMAdvisor | None = None


def get_llm() -> LLMAdvisor:
    global _llm
    if _llm is None:
        _llm = LLMAdvisor()
    return _llm
