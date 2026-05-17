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
    need_plan: bool
    steps: list[PlanStep] = field(default_factory=list)
    reason: str = ""


def should_skip_planning(intents: list[str], slots: dict | None = None) -> bool:
    """启发式判断是否跳过 Planning Agent，直接执行。

    跳过条件:
      - 单个意图（product_selection / supply_inquiry / report_lookup）
      - 多个独立意图（如同时查市场趋势+评论，无依赖）

    不跳过条件:
      - 含"对比""比较""vs"关键词 → 需要规划对比流程
      - 含"先...再..."链式表达 → 多步骤依赖
      - 含 product_compare + 其他意图 → 对比需要额外 step
    """
    if not intents:
        return True

    if len(intents) == 1:
        return True

    # 多意图时，无依赖关系就可以跳过
    dependent_pairs = [
        ({"product_compare"}, {"product_selection", "supply_inquiry"}),
    ]
    intent_set = set(intents)
    for a_set, b_set in dependent_pairs:
        if (intent_set & a_set) and (intent_set & b_set):
            return False

    return True


async def planning_agent(user_query: str, intents: list[str], slots: dict, context: dict | None = None) -> Plan:
    """让 LLM 生成多步执行计划。

    返回 Plan 结构，包含有序的 PlanStep 列表。
    """
    if not API_KEY:
        return _default_plan(intents)

    from openai import OpenAI
    from prompts import ProductScoutPrompts

    prompt = ProductScoutPrompts.intent_slot_recognize().format(
        conversation_history=json.dumps(context or {}, ensure_ascii=False)[:500],
        task_context=json.dumps({"intents": intents, "slots": slots}, ensure_ascii=False),
        user_preferences="无",
        query=f"请为以下选品需求生成执行计划。\n用户需求: {user_query}\n意图: {intents}\n槽位: {slots}\n\n"
              "输出 JSON: {{\"need_plan\": true, \"steps\": [{{\"step_id\": 1, \"description\": \"...\", \"agent\": \"MarketAgent\", \"depends_on\": []}}], \"reason\": \"...\"}}\n"
              "Agent 可选: MarketAgent(市场趋势) / ProfitAgent(利润测算) / SupplyRiskAgent(供应链风险) / ReviewInsightAgent(评论洞察)\n"
              "depends_on 填依赖的 step_id 列表。无依赖填 []。",
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
            agent_name=s.get("agent", "MarketAgent"),
            depends_on=s.get("depends_on", []),
        ))

    return Plan(
        need_plan=data.get("need_plan", len(steps) > 0),
        steps=steps,
        reason=data.get("reason", ""),
    )


def _default_plan(intents: list[str]) -> Plan:
    """默认计划：所有意图并行执行"""
    agent_map = {
        "product_selection": ["MarketAgent", "ProfitAgent"],
        "supply_inquiry": ["SupplyRiskAgent"],
        "product_compare": ["MarketAgent", "ReviewInsightAgent"],
    }
    steps = []
    step_id = 1
    for intent in intents:
        for agent in agent_map.get(intent, ["MarketAgent"]):
            steps.append(PlanStep(step_id=step_id, description=f"{intent}", agent_name=agent))
            step_id += 1
    return Plan(need_plan=len(steps) > 0, steps=steps, reason="默认并行执行")
