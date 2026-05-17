"""
意图分类 + 槽位抽取服务
"""
from __future__ import annotations

import json
import re

from config import API_KEY, LLM_MODEL, LLM_TEMPERATURE, MOCK_LLM
from create_logger import get_logger
from schemas import IntentResult

logger = get_logger("intent_service")

# ── 必填槽位定义 ──────────────────────────────────────

_REQUIRED_SLOTS = {
    "product_selection": ["category"],
    "product_compare": ["target_product_ids"],
    "supply_inquiry": ["category"],
    "report_lookup": [],
    "slot_reply": [],
    "general_chat": [],
}

# ── 兜底规则 ──────────────────────────────────────────

_INTENT_RULES = [
    (r"报告|记录|上次|之前|历史|结果|上回", "report_lookup"),
    (r"对比|比较|哪个好|哪个更|vs| versus ", "product_compare"),
    (r"供应|供应商|交期|风险|物流|发货|MOQ|起订", "supply_inquiry"),
    (r"选品|找产品|上新|推荐|帮我选|帮我找|有什么.*品", "product_selection"),
]


def _extract_slots_rule(msg: str) -> dict:
    """用规则从消息中提取基本槽位"""
    slots: dict = {}

    # category — 电商常见类目
    cat_patterns = [
        r"(家居[小]*电器|厨房[小]*电器|数码配件|手机配件|美妆|护肤|服饰|女装|男装|童装|鞋靴|箱包|玩具|母婴|运动户外|宠物用品|汽车用品|办公用品|文具)",
    ]
    for pat in cat_patterns:
        m = re.search(pat, msg)
        if m:
            slots["category"] = m.group(1)
            break

    # price_min / price_max — 价格区间
    price_range = re.findall(r"(\d+)\s*[-～~到至]\s*(\d+)\s*(?:元|块)?", msg)
    if price_range:
        slots["price_min"] = int(price_range[0][0])
        slots["price_max"] = int(price_range[0][1])

    # season
    if re.search(r"夏|夏天|夏季", msg):
        slots["season"] = "夏季"
    elif re.search(r"冬|冬天|冬季", msg):
        slots["season"] = "冬季"
    elif re.search(r"春|春天|春季", msg):
        slots["season"] = "春季"
    elif re.search(r"秋|秋天|秋季", msg):
        slots["season"] = "秋季"

    # preferences
    prefs = []
    if re.search(r"高利润|利润率高|利润高|毛利高", msg):
        prefs.append("高利润")
    if re.search(r"低竞争|竞争不|竞争小", msg):
        prefs.append("低竞争")
    if re.search(r"爆款|热销|好卖|火", msg):
        prefs.append("热销")
    if prefs:
        slots["preferences"] = prefs

    return slots


def _rule_based_classify(user_message: str) -> IntentResult:
    """基于关键词规则的意图分类"""
    msg = user_message.lower()

    # 先匹配意图规则
    matched_intent = None
    for pattern, intent in _INTENT_RULES:
        if re.search(pattern, msg):
            matched_intent = intent
            break

    # 短消息（无明确意图关键词）→ slot_reply
    if not matched_intent and len(msg) <= 8:
        return IntentResult(
            intent="slot_reply",
            confidence=0.5,
            slots={},
            slots_missing=[],
            slots_ambiguous=[],
        )

    if not matched_intent:
        return IntentResult(intent="general_chat", confidence=0.4)

    # 提取槽位并判断缺失
    slots = _extract_slots_rule(user_message)
    missing = _REQUIRED_SLOTS.get(matched_intent, [])
    slots_missing = [s for s in missing if not slots.get(s)]

    return IntentResult(
        intent=matched_intent,
        confidence=0.6,
        slots=slots,
        slots_missing=slots_missing,
        slots_ambiguous=[],
    )


def _llm_classify(user_message: str, context_json: str) -> IntentResult:
    """基于 LLM 的意图分类 + 槽位抽取"""
    from openai import OpenAI
    from prompts import INTENT_CLASSIFY_AND_SLOT_V1

    prompt = INTENT_CLASSIFY_AND_SLOT_V1.format(
        user_query=user_message,
        context_json=context_json or "{}",
    )

    try:
        client = OpenAI(api_key=API_KEY, base_url=__import__("config").BASE_URL)
        completion = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是电商选品对话助手。只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=LLM_TEMPERATURE,
        )
        text = completion.choices[0].message.content or "{}"
    except Exception as e:
        logger.warning("LLM 意图分类失败，降级为规则兜底: %s", e)
        return _rule_based_classify(user_message)

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
                return _rule_based_classify(user_message)
        else:
            return _rule_based_classify(user_message)

    return IntentResult(
        intent=data.get("intent", "general_chat"),
        confidence=float(data.get("confidence", 0.5)),
        slots=data.get("slots", {}),
        slots_missing=data.get("slots_missing", []),
        slots_ambiguous=data.get("slots_ambiguous", []),
    )


class IntentClassifier:
    """意图分类器"""

    @staticmethod
    def classify(user_message: str, context_json: str = "{}") -> IntentResult:
        """分类用户意图 + 抽取槽位"""
        if not user_message or not user_message.strip():
            return IntentResult(intent="general_chat", confidence=0.0)

        if MOCK_LLM or not API_KEY:
            logger.info("使用规则兜底进行意图分类")
            return _rule_based_classify(user_message)

        return _llm_classify(user_message, context_json)

    @staticmethod
    def slots_complete(intent: str, slots: dict) -> bool:
        """判断当前槽位是否足够执行"""
        required = _REQUIRED_SLOTS.get(intent, [])
        for slot in required:
            val = slots.get(slot)
            if val is None or val == "" or (isinstance(val, list) and len(val) == 0):
                return False
        return True
