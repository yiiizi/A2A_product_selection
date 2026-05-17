"""
用户意图识别服务 — 判断用户的业务场景/角色/深层动机
"""
from __future__ import annotations

import json
import re

from config import API_KEY, LLM_MODEL, LLM_TEMPERATURE, MOCK_LLM
from create_logger import get_logger
from schemas import UserIntent

logger = get_logger("user_intent_service")

# ── 兜底规则 ──────────────────────────────────────────

_RULES = [
    # (regex, dimension, value)
    (r"新手|第一次|不懂|入门|小白|刚做|刚开始", "experience_level", "newbie"),
    (r"资深|多年|老手|熟手|专业", "experience_level", "veteran"),
    (r"利润|毛利|ROI|成本|赚钱|回报|净利", "goal", "profit_first"),
    (r"走量|销量高|跑量|出单|起量", "goal", "volume_first"),
    (r"稳|低风险|退货率|售后少|靠谱|安全", "goal", "risk_averse"),
    (r"爆款|火|趋势|热门|流行|好卖|热销", "goal", "trend_chasing"),
    (r"急|马上|这周|快|赶紧|尽快", "urgency", "urgent"),
    (r"准备|打算|下个月|规划|过段时间|考虑", "urgency", "planned"),
    (r"看看|了解一下|有什么|浏览", "urgency", "exploring"),
    (r"先试试|测试|少量|几个|试水|试卖", "scale", "trial"),
    (r"大批|大量|集装箱|托盘|批量|几百上千|万件", "scale", "bulk"),
    (r"新店|刚开|刚开始做|开店|第一次做", "scenario", "new_store"),
    (r"补货|再进|卖完了|断货|加单|追单", "scenario", "restock"),
    (r"夏天|冬季|换季|应季|季节|春夏|秋冬|圣诞|春节|双11|618", "scenario", "seasonal"),
    (r"清仓|甩卖|尾货|处理|清货|库存处理", "scenario", "clearance"),
]


def _rule_based_recognize(user_message: str) -> UserIntent:
    """基于关键词规则的用户意图识别"""
    result = {
        "experience_level": "intermediate",
        "urgency": "exploring",
        "goal": "profit_first",
        "scale": "small_batch",
        "scenario": "exploring",
    }

    for pattern, dim, val in _RULES:
        if re.search(pattern, user_message):
            result[dim] = val

    return UserIntent(**result, confidence=0.6)


def _llm_recognize(user_message: str, history: list[dict]) -> UserIntent:
    """基于 LLM 的用户意图识别"""
    from openai import OpenAI
    from prompts import USER_INTENT_RECOGNIZE_V1

    history_text = json.dumps(
        [{"role": m.get("role", ""), "content": m.get("content", "")[:200]}
         for m in (history or [])[-6:]],
        ensure_ascii=False,
    )

    prompt = USER_INTENT_RECOGNIZE_V1.format(
        user_query=user_message,
        history=history_text,
    )

    try:
        client = OpenAI(api_key=API_KEY, base_url=__import__("config").BASE_URL)
        completion = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是电商选品场景分析助手。只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=LLM_TEMPERATURE,
        )
        text = completion.choices[0].message.content or "{}"
    except Exception as e:
        logger.warning("LLM 用户意图识别失败，降级为规则兜底: %s", e)
        return _rule_based_recognize(user_message)

    # 解析 JSON
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            try:
                data = json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                logger.warning("LLM 用户意图 JSON 解析失败，降级为规则兜底")
                return _rule_based_recognize(user_message)
        else:
            logger.warning("LLM 用户意图无 JSON，降级为规则兜底")
            return _rule_based_recognize(user_message)

    return UserIntent(
        experience_level=data.get("experience_level", "intermediate"),
        urgency=data.get("urgency", "planned"),
        goal=data.get("goal", "profit_first"),
        scale=data.get("scale", "small_batch"),
        scenario=data.get("scenario", "exploring"),
        confidence=float(data.get("confidence", 0.5)),
    )


class UserIntentRecognizer:
    """用户意图识别器"""

    @staticmethod
    def recognize(user_message: str, history: list[dict] | None = None) -> UserIntent:
        """识别用户意图"""
        if not user_message or not user_message.strip():
            return UserIntent(confidence=0.0)

        history = history or []

        if MOCK_LLM or not API_KEY:
            logger.info("使用规则兜底进行用户意图识别")
            return _rule_based_recognize(user_message)

        return _llm_recognize(user_message, history)

    @staticmethod
    def influence_slots(user_intent: UserIntent, slots: dict) -> dict:
        """根据用户意图调整槽位默认值"""
        slots = dict(slots)  # 不修改原始 dict

        # goal → profit_requirement
        if user_intent.goal == "profit_first" and not slots.get("profit_requirement"):
            slots["profit_requirement"] = "high"
        elif user_intent.goal == "volume_first" and not slots.get("profit_requirement"):
            slots["profit_requirement"] = "medium"

        # scenario → season
        if user_intent.scenario == "seasonal" and not slots.get("season"):
            from datetime import datetime
            month = datetime.now().month
            if month in [3, 4, 5]:
                slots["season"] = "春季"
            elif month in [6, 7, 8]:
                slots["season"] = "夏季"
            elif month in [9, 10, 11]:
                slots["season"] = "秋季"
            else:
                slots["season"] = "冬季"

        # scale → price_max
        if user_intent.scale == "trial" and not slots.get("price_max"):
            slots["price_max"] = 200
        elif user_intent.scale == "bulk" and not slots.get("price_max"):
            slots["price_min"] = slots.get("price_min", 50)

        return slots

    @staticmethod
    def influence_weights(user_intent: UserIntent, weights: dict) -> dict:
        """根据用户意图调整评分权重"""
        weights = dict(weights)  # 不修改原始

        if user_intent.experience_level == "newbie":
            weights["review_score"] = weights.get("review_score", 0.10) + 0.05
            weights["risk_score"] = max(0.02, weights.get("risk_score", 0.10) - 0.05)
        elif user_intent.experience_level == "veteran":
            weights["profit_score"] = weights.get("profit_score", 0.25) + 0.05

        if user_intent.goal == "risk_averse":
            weights["supply_score"] = weights.get("supply_score", 0.15) + 0.05
            weights["risk_score"] = weights.get("risk_score", 0.10) + 0.05
        elif user_intent.goal == "trend_chasing":
            weights["trend_score"] = weights.get("trend_score", 0.20) + 0.05

        if user_intent.scale == "trial":
            weights["risk_score"] = max(0.02, weights.get("risk_score", 0.10) - 0.05)

        return weights
