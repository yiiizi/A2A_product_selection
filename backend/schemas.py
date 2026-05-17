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
    request_id: str
    data: SelectionReport


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
