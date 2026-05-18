from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── 请求 / 响应 ──────────────────────────────────────

class UserIntent(BaseModel):
    """用户意图 — 识别用户的业务场景/角色/深层动机"""
    experience_level: str = "intermediate"  # newbie / intermediate / veteran
    urgency: str = "planned"                # urgent / planned / exploring
    goal: str = "profit_first"              # profit_first / volume_first / risk_averse / trend_chasing
    scale: str = "small_batch"              # trial / small_batch / bulk
    scenario: str = "exploring"             # new_store / restock / seasonal / clearance / exploring
    confidence: float = 0.5


class IntentResult(BaseModel):
    """意图分类 + 槽位抽取结果"""
    intent: str = "general_chat"  # product_selection / report_lookup / product_compare / supply_inquiry / slot_reply / general_chat
    confidence: float = 0.5
    slots: dict = Field(default_factory=dict)
    slots_missing: list[str] = Field(default_factory=list)
    slots_ambiguous: list[str] = Field(default_factory=list)


class SelectionRequest(BaseModel):
    query: str = Field(..., description="用户自然语言选品需求")
    top_k: int = Field(default=5, ge=1, le=20, description="返回商品数量")


class Constraints(BaseModel):
    category: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    season: str | None = None
    preferences: list[str] = Field(default_factory=list)


class AgentResult(BaseModel):
    agent: str
    product_id: int
    status: str = "success"  # success | failed | partial
    scores: dict[str, float] = Field(default_factory=dict)
    summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    suggestions: list[str] = Field(default_factory=list)
    error: str | None = None


class ProductAnalysisResult(BaseModel):
    product_id: int
    product_name: str = ""
    category: str = ""
    final_score: float = 0.0
    rank: int = 0
    agent_results: dict[str, AgentResult] = Field(default_factory=dict)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    recommendation: str = "neutral"  # recommend | neutral | not_recommend
    highlights: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class SelectionReport(BaseModel):
    request_id: str
    query: str
    constraints: Constraints = Field(default_factory=Constraints)
    products: list[ProductAnalysisResult] = Field(default_factory=list)
    final_report: str = ""
    created_at: datetime = Field(default_factory=datetime.now)


class SelectionResponse(BaseModel):
    status: str = "success"
    request_id: str = ""
    data: SelectionReport | None = None


class ErrorResponse(BaseModel):
    status: str = "error"
    request_id: str = ""
    message: str = ""
    error_code: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


# ── 聊天 / 会话 ──────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str = Field(..., description="会话ID (前端 UUID v4)")
    message: str = Field(..., description="用户输入")


class ChatMessage(BaseModel):
    role: str = "assistant"          # user / assistant / system
    content: str = ""                # Markdown 文本
    message_type: str = "text"       # text / options / slot_prompt / product_card / report_card
    timestamp: datetime = Field(default_factory=datetime.now)


class FollowUp(BaseModel):
    question: str = ""               # 追问文本
    options: list[str] = Field(default_factory=list)  # 快捷选项
    missing_slots: list[str] = Field(default_factory=list)


class ChatResult(BaseModel):
    result_type: str = ""            # selection_report / report_summary / comparison / supply_advice
    products: list[ProductAnalysisResult] = Field(default_factory=list)
    report: str = ""                 # Markdown 报告文本
    quick_actions: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    session_id: str = ""
    message: ChatMessage = Field(default_factory=ChatMessage)
    follow_up: FollowUp | None = None
    result: ChatResult | None = None


# ── Planning / Agent 调度 ─────────────────────────────

class PlanStep(BaseModel):
    """单个执行步骤"""
    step_id: int
    description: str = ""              # "分析市场趋势和竞品"
    agent_name: str = ""               # "MarketAgent"
    depends_on: list[int] = Field(default_factory=list)
    priority: int = 1                  # 1=高 2=中 3=低


class Plan(BaseModel):
    """Planning Agent 结构化输出"""
    primary_intent: str = "product_selection"
    required_agents: list[str] = Field(default_factory=list)
    skip_agents: list[str] = Field(default_factory=list)
    skip_reason: str = ""
    steps: list[PlanStep] = Field(default_factory=list)
    confidence: float = 0.8


class SlotDef(BaseModel):
    """Agent 专属槽位定义"""
    key: str
    label: str = ""
    required: bool = False
    default: Any = None
    source: str = "db"                 # db / user / derived


class AgentConfig(BaseModel):
    """Agent 配置：URL + 专属槽位 + 超时策略"""
    name: str
    url: str
    required_slots: dict[str, SlotDef] = Field(default_factory=dict)
    timeout: int = 120
    priority: int = 1
    fallback_enabled: bool = True


class AgentOutput(BaseModel):
    """Agent 标准化输出"""
    agent: str
    product_id: int
    status: str = "success"            # success / failed / partial / need_more_info
    raw_data: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    scores: dict[str, float] = Field(default_factory=dict)
    suggestions: list[str] = Field(default_factory=list)
    error: str | None = None
    fallback: bool = False             # 是否降级

    @classmethod
    def merge(cls, agent_name: str, outputs: list[AgentOutput]) -> AgentOutput:
        """聚合多个商品的分析结果为单个 Agent 输出"""
        if not outputs:
            return cls(agent=agent_name, product_id=0, status="failed", error="无结果")
        summaries = [o.summary for o in outputs if o.summary]
        suggestions = list(dict.fromkeys(s for o in outputs for s in o.suggestions))
        all_scores = [o.scores for o in outputs if o.scores]
        avg_scores = {}
        if all_scores:
            for key in all_scores[0]:
                vals = [s[key] for s in all_scores if key in s]
                avg_scores[key] = round(sum(vals) / len(vals), 1) if vals else 0
        return cls(
            agent=agent_name,
            product_id=outputs[0].product_id,
            status="success" if all(o.status == "success" for o in outputs) else "partial",
            raw_data={o.product_id: o.raw_data for o in outputs},
            summary="; ".join(summaries),
            scores=avg_scores,
            suggestions=suggestions,
        )


class SlotValidationResult(BaseModel):
    """Agent 槽位校验结果"""
    ready: bool
    missing_slots: list[str] = Field(default_factory=list)
    question: str = ""
