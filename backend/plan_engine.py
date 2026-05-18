"""
智能任务规划引擎 — Planning Agent

在意图识别后，判断任务复杂度：
  - 简单查询 → 直接执行（跳过 Planning，省 1 次 LLM 调用）
  - 复杂查询 → LLM 生成多步计划 → 按依赖关系串行/并行执行
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from config import API_KEY, BASE_URL, LLM_MODEL, LLM_TEMPERATURE
from create_logger import get_logger

logger = get_logger("plan_engine")


@dataclass
class PlanStep:
    step_id: int
    description: str          # 自然语言描述，如"分析市场趋势"
    agent_name: str           # MarketAgent / ProfitAgent / SupplyRiskAgent / ReviewInsightAgent
    depends_on: list[int] = field(default_factory=list)  # 依赖的 step_id


@dataclass
class Plan:
    """结构化执行计划 — 包含 Agent 路由决策"""
    need_plan: bool
    primary_intent: str = "product_selection"
    required_agents: list[str] = field(default_factory=list)
    skip_agents: list[str] = field(default_factory=list)
    skip_reason: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    reason: str = ""
    confidence: float = 0.8


def should_skip_planning(intents: list[str], slots: dict | None = None) -> bool:
    """[兼容保留] 旧的布尔判断，等同于 should_skip_planning_llm() is not None"""
    return should_skip_planning_llm(intents, slots) is not None


_ALL_AGENTS = ["MarketAgent", "ProfitAgent", "SupplyRiskAgent", "ReviewInsightAgent"]


def should_skip_planning_llm(intents: list[str], slots: dict | None = None) -> Plan | None:
    """启发式判断：如果可以确定 Agent 组合则直接返回 Plan (跳过 LLM Planning)；
    返回 None 表示需要 LLM 规划。

    设计目标: 简单场景省掉 1 次 LLM 调用 (~800 token)。
    """
    slots = slots or {}
    intent = intents[0] if intents else "product_selection"

    # supply_inquiry → 只需 SupplyRiskAgent
    if intent == "supply_inquiry":
        return Plan(
            need_plan=True,
            primary_intent=intent,
            required_agents=["SupplyRiskAgent"],
            skip_agents=[a for a in _ALL_AGENTS if a != "SupplyRiskAgent"],
            skip_reason="供应链咨询只需 SupplyRiskAgent",
            confidence=0.95,
        )

    # report_lookup → 无需 Agent
    if intent == "report_lookup":
        return Plan(
            need_plan=False,
            primary_intent=intent,
            required_agents=[],
            skip_agents=list(_ALL_AGENTS),
            skip_reason="历史报告查询不需要 Agent 分析",
            confidence=0.95,
        )

    # slot_reply / general_chat → 无需 Agent
    if intent in ("slot_reply", "general_chat"):
        return Plan(
            need_plan=False,
            primary_intent=intent,
            required_agents=[],
            skip_agents=list(_ALL_AGENTS),
            skip_reason=f"意图={intent}，不需要 Agent",
            confidence=0.9,
        )

    # product_compare → Market + Review
    if intent == "product_compare":
        return Plan(
            need_plan=True,
            primary_intent=intent,
            required_agents=["MarketAgent", "ReviewInsightAgent"],
            skip_agents=["ProfitAgent", "SupplyRiskAgent"],
            skip_reason="商品对比只需市场和评论分析",
            confidence=0.9,
        )

    # product_selection: 只有 category 缺乏完整上下文 → 先查市场
    if intent == "product_selection":
        has_full_context = bool(
            slots.get("category")
            and (slots.get("price_min") is not None or slots.get("price_max") is not None)
            and slots.get("season")
        )
        if not has_full_context:
            return Plan(
                need_plan=True,
                primary_intent=intent,
                required_agents=["MarketAgent"],
                skip_agents=["ProfitAgent", "SupplyRiskAgent", "ReviewInsightAgent"],
                skip_reason="槽位不完整，先用 MarketAgent 探市场，待补充后再追加分析",
                confidence=0.8,
            )

    # 多意图依赖检测 → 需要 LLM 规划
    if len(intents) > 1:
        dependent_pairs = [
            ({"product_compare"}, {"product_selection", "supply_inquiry"}),
            ({"supply_inquiry"}, {"product_selection"}),
        ]
        intent_set = set(intents)
        for a_set, b_set in dependent_pairs:
            if (intent_set & a_set) and (intent_set & b_set):
                return None  # 需要 LLM 规划

    # 其他情况: 完整槽位 + 产品选品 → 需要 LLM 规划
    return None


async def planning_agent(user_query: str, intents: list[str], slots: dict, context: dict | None = None) -> Plan:
    """让 LLM 生成多步执行计划。

    返回 Plan 结构，包含有序的 PlanStep 列表。
    """
    if not API_KEY:
        return _default_plan(intents)

    from openai import OpenAI
    from prompts import ProductScoutPrompts

    prompt_text = (
        f"用户需求: {user_query}\n意图: {intents}\n槽位: {json.dumps(slots, ensure_ascii=False)}\n\n"
        "请决定需要调用哪些 A2A Agent，并给出执行步骤。\n\n"
        "Agent 清单:\n"
        "- MarketAgent: 市场趋势 + 竞品分析 + 价格带\n"
        "- ProfitAgent: 利润测算 + 建议售价 + 盈亏平衡\n"
        "- SupplyRiskAgent: 供应商评估 + 合规风险 + 备货建议\n"
        "- ReviewInsightAgent: 评论 RAG 检索 + 痛点提取 + 卖点机会\n\n"
        "决策原则:\n"
        "1. 只选与用户需求直接相关的 Agent，能少则少\n"
        "2. 用户没提利润/价格 → 不选 ProfitAgent\n"
        "3. 用户没提风险/供应商 → 不选 SupplyRiskAgent\n"
        "4. 用户没提评论/口碑 → 不选 ReviewInsightAgent\n"
        "5. 简单查询可只用 MarketAgent\n\n"
        '输出 JSON:\n'
        '{{\n'
        '  "primary_intent": "product_selection",\n'
        '  "required_agents": ["MarketAgent", "ProfitAgent"],\n'
        '  "skip_agents": ["SupplyRiskAgent", "ReviewInsightAgent"],\n'
        '  "skip_reason": "用户关注利润,不需要供应链和评论分析",\n'
        '  "need_plan": true,\n'
        '  "steps": [\n'
        '    {{"step_id": 1, "description": "分析市场", "agent_name": "MarketAgent", "depends_on": []}}\n'
        '  ],\n'
        '  "reason": "共2步并行"\n'
        '}}'
    )

    prompt = ProductScoutPrompts.intent_slot_recognize().format(
        conversation_history=json.dumps(context or {}, ensure_ascii=False)[:500],
        task_context=json.dumps({"intents": intents, "slots": slots}, ensure_ascii=False),
        user_preferences="无",
        query=prompt_text,
    )

    try:
        client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        completion = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是任务规划专家。分析需求，输出结构化的多步执行计划。只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=LLM_TEMPERATURE,
        )
        text = completion.choices[0].message.content or "{}"
    except Exception as e:
        logger.warning("Planning Agent 调用失败，使用默认计划: %s", e)
        return _default_plan(intents)

    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            cleaned = "\n".join(lines)
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        data = json.loads(cleaned[start:end + 1]) if start != -1 else {}

    steps = []
    for s in data.get("steps", []):
        steps.append(PlanStep(
            step_id=s.get("step_id", len(steps) + 1),
            description=s.get("description", ""),
            agent_name=s.get("agent_name", s.get("agent", "MarketAgent")),
            depends_on=s.get("depends_on", []),
        ))

    required = data.get("required_agents", [])
    skip = data.get("skip_agents", [])

    # 如果 LLM 没返回 required_agents, 从 steps 中提取
    if not required and steps:
        required = list(dict.fromkeys(s.agent_name for s in steps))

    return Plan(
        need_plan=data.get("need_plan", len(steps) > 0),
        primary_intent=data.get("primary_intent", intents[0] if intents else "product_selection"),
        required_agents=required,
        skip_agents=skip,
        skip_reason=data.get("skip_reason", ""),
        steps=steps,
        reason=data.get("reason", ""),
        confidence=float(data.get("confidence", 0.8)),
    )


def _default_plan(intents: list[str]) -> Plan:
    """默认计划：所有意图并行执行"""
    agent_map = {
        "product_selection": ["MarketAgent", "ProfitAgent"],
        "supply_inquiry": ["SupplyRiskAgent"],
        "product_compare": ["MarketAgent", "ReviewInsightAgent"],
    }
    required: list[str] = []
    steps = []
    step_id = 1
    for intent in intents:
        for agent in agent_map.get(intent, ["MarketAgent"]):
            if agent not in required:
                required.append(agent)
            steps.append(PlanStep(step_id=step_id, description=f"{intent}", agent_name=agent))
            step_id += 1
    return Plan(
        need_plan=len(steps) > 0,
        primary_intent=intents[0] if intents else "product_selection",
        required_agents=required,
        skip_agents=[],
        skip_reason="",
        steps=steps,
        reason="默认并行执行",
    )
