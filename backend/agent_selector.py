"""
Agent Selector — 根据 Plan + UserIntent + Slots 动态决定调用哪些 Agent。

核心原则:
    以 Plan 为准，用户意图和槽位为辅助，槽位为硬约束。
"""

from __future__ import annotations

from config import (
    MARKET_A2A_URL, PROFIT_A2A_URL, SUPPLY_RISK_A2A_URL, REVIEW_A2A_URL,
)
from create_logger import get_logger
from schemas import AgentConfig, Plan, UserIntent

logger = get_logger("agent_selector")

# ── Agent URL 映射 ──────────────────────────────────

A2A_AGENTS: dict[str, str] = {
    "MarketAgent": MARKET_A2A_URL,
    "ProfitAgent": PROFIT_A2A_URL,
    "SupplyRiskAgent": SUPPLY_RISK_A2A_URL,
    "ReviewInsightAgent": REVIEW_A2A_URL,
}

# ── Agent 专属槽位定义 (Phase 3 接入) ────────────────

AGENT_SLOTS: dict[str, dict] = {
    "MarketAgent": {},
    "ProfitAgent": {},
    "SupplyRiskAgent": {},
    "ReviewInsightAgent": {},
}

# ── 规则矩阵 ─────────────────────────────────────────

_AGENT_RULES: dict[str, dict] = {
    "product_selection": {
        "always": ["MarketAgent"],
        "conditional": {
            "ProfitAgent": lambda intent, slots: (
                intent.goal == "profit_first"
                or intent.experience_level == "veteran"
                or "高利润" in slots.get("preferences", [])
            ),
            "SupplyRiskAgent": lambda intent, slots: (
                intent.goal == "risk_averse"
                or intent.experience_level == "newbie"
                or "低风险" in slots.get("preferences", [])
                or "稳定" in slots.get("preferences", [])
            ),
            "ReviewInsightAgent": lambda intent, slots: (
                intent.goal == "trend_chasing"
                or intent.experience_level == "newbie"
                or "热销" in slots.get("preferences", [])
                or "爆款" in slots.get("preferences", [])
            ),
        },
    },
    "supply_inquiry": {
        "always": ["SupplyRiskAgent"],
        "conditional": {
            "MarketAgent": lambda intent, slots: slots.get("category") is not None,
        },
    },
    "product_compare": {
        "always": ["MarketAgent", "ReviewInsightAgent"],
        "conditional": {
            "ProfitAgent": lambda intent, slots: intent.goal == "profit_first",
        },
    },
    "report_lookup": {
        "always": [],
        "conditional": {},
    },
    "slot_reply": {
        "always": [],
        "conditional": {},
    },
    "general_chat": {
        "always": [],
        "conditional": {},
    },
}


class AgentSelector:
    """动态 Agent 选择器"""

    @staticmethod
    def select(
        plan: Plan | None,
        user_intent: UserIntent | None = None,
        slots: dict | None = None,
    ) -> dict[str, AgentConfig]:
        """
        核心选择方法。

        决策顺序:
          1. Plan.required_agents 非空 → 以 Plan 为准
          2. Plan 为空 → 走规则路由
          3. 兜底: 至少 MarketAgent

        返回: {agent_name: AgentConfig}
        """

        # ── 1. Plan 驱动 ────────────────────────────
        if plan is not None and plan.required_agents:
            skip = set(plan.skip_agents)
            agents: dict[str, AgentConfig] = {}
            for agent_name in plan.required_agents:
                if agent_name in skip:
                    logger.info("Plan 跳过 Agent: %s", agent_name)
                    continue
                url = A2A_AGENTS.get(agent_name)
                if url is None:
                    logger.warning("未知 Agent: %s, 跳过", agent_name)
                    continue
                agents[agent_name] = AgentConfig(
                    name=agent_name,
                    url=url,
                    required_slots=AGENT_SLOTS.get(agent_name, {}),
                )
            if agents:
                logger.info("Plan 驱动选择: %s (跳过: %s)", list(agents.keys()), list(skip))
                return agents
            # required_agents 全被 skip 了, 继续走规则兜底

        # ── 2. 规则路由 ────────────────────────────
        intent = "product_selection"
        if plan is not None and plan.primary_intent:
            intent = plan.primary_intent

        slots = slots or {}
        ui = user_intent or UserIntent()

        rules = _AGENT_RULES.get(intent)
        if rules is None:
            rules = _AGENT_RULES["product_selection"]

        agents = {}
        skip_from_plan = set(plan.skip_agents) if plan is not None else set()

        # always
        for agent_name in rules.get("always", []):
            if agent_name in skip_from_plan:
                continue
            url = A2A_AGENTS.get(agent_name)
            if url is None:
                continue
            agents[agent_name] = AgentConfig(
                name=agent_name,
                url=url,
                required_slots=AGENT_SLOTS.get(agent_name, {}),
            )

        # conditional
        for agent_name, condition in rules.get("conditional", {}).items():
            if agent_name in skip_from_plan or agent_name in agents:
                continue
            try:
                if condition(ui, slots):
                    url = A2A_AGENTS.get(agent_name)
                    if url is None:
                        continue
                    agents[agent_name] = AgentConfig(
                        name=agent_name,
                        url=url,
                        required_slots=AGENT_SLOTS.get(agent_name, {}),
                    )
            except Exception:
                logger.exception("条件判断失败: agent=%s", agent_name)

        # ── 3. 兜底: 至少 MarketAgent ────────────────
        if not agents:
            url = A2A_AGENTS["MarketAgent"]
            agents["MarketAgent"] = AgentConfig(
                name="MarketAgent",
                url=url,
                required_slots=AGENT_SLOTS.get("MarketAgent", {}),
            )
            logger.info("无 Agent 选中, 兜底 MarketAgent")

        logger.info(
            "规则路由选择: intent=%s agents=%s",
            intent, list(agents.keys()),
        )
        return agents
