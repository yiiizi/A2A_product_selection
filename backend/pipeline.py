"""
统一选品流水线 (Unified Selection Pipeline)

同时服务于:
  - POST /api/selection/analyze     (非流式, 返回 SelectionReport)
  - POST /api/chat                  (SSE 流式, 通过 session_orchestrator)

全链路: Intent → UserIntent → Slot → Planning → AgentSelector →
        SlotValidator → Candidate Query → Agent Dispatch → Report

避免 /analyze 和 /session/chat 各走各的架构分裂。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from create_logger import get_logger

logger = get_logger("pipeline")

# ── 非流式入口: /analyze 调用 ────────────────────────


async def run_full_pipeline(
    user_query: str,
    top_k: int = 5,
    pre_slots: dict | None = None,
    pre_intent: str | None = None,
    pre_user_intent=None,
) -> dict:
    """
    非流式全链路选品分析。

    返回:
        {
            "request_id": str,
            "report": SelectionReport,
            "plan": Plan,
            "agents_used": list[str],
        }
    """
    from schemas import Constraints, Plan, SelectionReport, SelectionRequest, UserIntent

    request_id = f"req-{datetime.now().strftime('%Y%m%d')}-{__import__('uuid').uuid4().hex[:6]}"

    # ── 阶段1: 意图分类 ──────────────────────────
    if pre_intent is None:
        from intent_service import IntentClassifier
        intent_result = IntentClassifier.classify(user_query)
        intent = intent_result.intent
        slots = pre_slots or intent_result.slots
    else:
        intent = pre_intent
        slots = pre_slots or {}

    logger.info("[%s] 意图=%s 槽位=%s", request_id, intent, slots)

    # ── 阶段2: 用户画像 ──────────────────────────
    if pre_user_intent is None:
        try:
            from user_intent_service import UserIntentRecognizer
            user_intent = UserIntentRecognizer.recognize(user_query)
        except Exception:
            user_intent = UserIntent()
    else:
        user_intent = pre_user_intent

    # ── 阶段3: Planning ──────────────────────────
    plan = await _resolve_plan(intent, slots, user_query)

    if not plan.required_agents:
        report = SelectionReport(
            request_id=request_id,
            query=user_query,
            products=[],
            final_report=plan.skip_reason or "根据分析，当前查询无需调用 Agent。",
        )
        return {
            "request_id": request_id,
            "report": report,
            "plan": plan,
            "agents_used": [],
        }

    # ── 阶段4: AgentSelector ─────────────────────
    from agent_selector import AgentSelector
    agents = AgentSelector.select(plan=plan, user_intent=user_intent, slots=slots)
    logger.info("[%s] 选定 Agent: %s", request_id, list(agents.keys()))

    # ── 阶段5: 候选商品查询 ──────────────────────
    constraints = _build_constraints(slots, intent)
    candidates = _query_candidates(constraints, top_k * 3)
    if not candidates:
        report = SelectionReport(
            request_id=request_id,
            query=user_query,
            constraints=constraints,
            products=[],
            final_report="没有找到符合条件的候选商品，请尝试放宽价格区间或类目条件。",
        )
        return {
            "request_id": request_id,
            "report": report,
            "plan": plan,
            "agents_used": list(agents.keys()),
        }

    products_to_analyze = candidates[: max(3, top_k // 2)]

    # ── 阶段6: Agent Slot 校验 ───────────────────
    if candidates:
        from slot_manager import AgentSlotValidator
        validations = AgentSlotValidator.validate_all(
            list(agents.keys()), slots, product_id=candidates[0].get("product_id"),
        )
        failed = [v for v in validations if not v.ready]
        if failed:
            missing_text = "\n".join(v.question for v in failed)
            report = SelectionReport(
                request_id=request_id,
                query=user_query,
                constraints=constraints,
                products=[],
                final_report=f"部分 Agent 需要补充信息:\n{missing_text}",
            )
            return {
                "request_id": request_id,
                "report": report,
                "plan": plan,
                "agents_used": list(agents.keys()),
            }

    # ── 阶段7: Agent 并行调度 ────────────────────
    from agent_dispatcher import clear_mcp_cache, AGENT_SEMAPHORE, AGENT_TIMEOUTS, DEFAULT_AGENT_TIMEOUT
    from selection_service import analyze_single_product

    clear_mcp_cache()
    max_timeout = max(
        (AGENT_TIMEOUTS.get(name, DEFAULT_AGENT_TIMEOUT) for name in agents.keys()),
        default=DEFAULT_AGENT_TIMEOUT,
    )

    async def _analyze_one(product):
        async with AGENT_SEMAPHORE:
            return await asyncio.wait_for(
                analyze_single_product(product, constraints, user_query, agents=agents),
                timeout=max_timeout,
            )

    tasks = [_analyze_one(p) for p in products_to_analyze]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    products = []
    for r in raw_results:
        if isinstance(r, Exception):
            logger.error("[%s] 商品分析失败: %s", request_id, r)
            continue
        from schemas import ProductAnalysisResult
        if isinstance(r, ProductAnalysisResult):
            products.append(r)

    products.sort(key=lambda p: p.final_score, reverse=True)
    products = products[:top_k]
    for i, p in enumerate(products):
        p.rank = i + 1

    # ── 阶段8: Final LLM 报告 ────────────────────
    from selection_service import generate_report
    final_report = await generate_report(user_query, products)

    report = SelectionReport(
        request_id=request_id,
        query=user_query,
        constraints=constraints,
        products=products,
        final_report=final_report,
        created_at=datetime.now(),
    )

    # ── 阶段9: 持久化 ────────────────────────────
    from selection_service import save_selection_report, save_agent_logs
    save_selection_report(request_id, user_query, constraints, products, final_report)
    save_agent_logs(request_id, products)

    return {
        "request_id": request_id,
        "report": report,
        "plan": plan,
        "agents_used": list(agents.keys()),
    }


# ── 流式入口: session_orchestrator 调用 ──────────────


async def stream_full_pipeline(
    user_query: str,
    top_k: int,
    pre_intent: str,
    pre_slots: dict,
    pre_user_intent,
    context: dict | None = None,
) -> AsyncGenerator[dict, None]:
    """
    SSE 流式选品分析。逐步 yield {"event": "...", "data": {...}}。

    与 session_orchestrator._stream_selection() 的差异:
      - 包含了 Intent → Planning → AgentSelector 全链路
      - session_orchestrator 只负责 SSE 包装 + 会话管理
    """
    from schemas import Constraints, Plan, SelectionReport
    from session_service import SessionManager
    from selection_service import analyze_single_product, generate_report, query_candidate_products
    from selection_service import save_selection_report, save_agent_logs
    from agent_dispatcher import clear_mcp_cache, AGENT_SEMAPHORE, AGENT_TIMEOUTS, DEFAULT_AGENT_TIMEOUT

    intent = pre_intent
    slots = pre_slots
    user_intent = pre_user_intent
    request_id = f"req-{datetime.now().strftime('%Y%m%d')}-{__import__('uuid').uuid4().hex[:6]}"

    # ── Planning ──────────────────────────────────
    plan = await _resolve_plan(intent, slots, user_query)

    if not plan.required_agents:
        yield {"event": "delta", "data": {"content": plan.skip_reason or "当前查询无需调用 Agent。"}}
        yield {"event": "done", "data": {"message_type": "text"}}
        return

    yield {"event": "delta", "data": {
        "content": f"任务分析: 将调用 {', '.join(plan.required_agents)}"
                   + (f" (跳过 {', '.join(plan.skip_agents)})" if plan.skip_agents else "")
                   + f"\n{plan.skip_reason}\n\n"
    }}

    # ── AgentSelector ─────────────────────────────
    from agent_selector import AgentSelector
    agents = AgentSelector.select(plan=plan, user_intent=user_intent, slots=slots)
    logger.info("[%s] 流式-选定 Agent: %s", request_id, list(agents.keys()))

    # ── Slot Validator ────────────────────────────
    constraints = _build_constraints(slots, intent)
    candidates = query_candidate_products(constraints, min(top_k * 3, 20))

    if not candidates:
        yield {"event": "delta", "data": {"content": "没有找到符合条件的候选商品。"}}
        yield {"event": "done", "data": {"message_type": "text"}}
        return

    first_pid = candidates[0].get("product_id")
    from slot_manager import AgentSlotValidator
    validations = AgentSlotValidator.validate_all(list(agents.keys()), slots, product_id=first_pid)
    failed = [v for v in validations if not v.ready]
    if failed:
        yield {"event": "follow_up", "data": {
            "question": "\n".join(v.question for v in failed),
            "options": [],
            "missing_slots": [s for v in failed for s in v.missing_required],
            "agents": [v.name for v in failed],
        }}
        return

    # ── Yield plan info ────────────────────────────
    products_to_analyze = candidates[: min(3, top_k)]
    names = "、".join(p.get("product_name", "") for p in products_to_analyze)
    yield {"event": "delta", "data": {
        "content": f"已筛出 {len(products_to_analyze)} 个候选商品：{names}\n\n"
                   f"A2A Agent ({len(agents)} 个) 并行分析中...\n\n"
    }}

    # ── Agent Dispatch ─────────────────────────────
    clear_mcp_cache()
    max_timeout = max(
        (AGENT_TIMEOUTS.get(name, DEFAULT_AGENT_TIMEOUT) for name in agents.keys()),
        default=DEFAULT_AGENT_TIMEOUT,
    )

    async def _analyze_one(product):
        async with AGENT_SEMAPHORE:
            return await asyncio.wait_for(
                analyze_single_product(product, constraints, user_query, agents=agents),
                timeout=max_timeout,
            )

    tasks = [asyncio.create_task(_analyze_one(p)) for p in products_to_analyze]
    completed = []
    total = len(tasks)

    for done in asyncio.as_completed(tasks):
        try:
            product = await done
        except asyncio.TimeoutError:
            yield {"event": "delta", "data": {"content": f"有一个商品分析超时（{max_timeout}s），跳过。\n\n"}}
            continue
        except Exception as exc:
            yield {"event": "delta", "data": {"content": f"有一个商品分析失败：{exc}\n\n"}}
            continue

        completed.append(product)
        completed.sort(key=lambda p: p.final_score, reverse=True)
        for idx, item in enumerate(completed, start=1):
            item.rank = idx
        yield {"event": "products", "data": {"products": [p.model_dump() for p in completed]}}
        yield {"event": "delta", "data": {"content": _product_summary(product, len(completed), total)}}

    if not completed:
        yield {"event": "error", "data": {"message": "A2A Agent 没有返回可用结果。"}}
        return

    completed.sort(key=lambda p: p.final_score, reverse=True)
    products = completed[:top_k]
    for idx, p in enumerate(products, start=1):
        p.rank = idx

    yield {"event": "products", "data": {"products": [p.model_dump() for p in products]}}
    yield {"event": "delta", "data": {"content": "分析已完成，正在生成选品报告...\n\n"}}

    # ── Final Report ───────────────────────────────
    final_report = await generate_report(user_query, products)
    save_selection_report(request_id, user_query, constraints, products, final_report)
    save_agent_logs(request_id, products)

    yield {"event": "report_start", "data": {"message_type": "report_card"}}
    for chunk in _split_text(final_report, 80):
        yield {"event": "report_delta", "data": {"content": chunk}}
        await asyncio.sleep(0.03)

    yield {"event": "done", "data": {"message_type": "report_card", "request_id": request_id}}


# ── 内部辅助函数 ─────────────────────────────────────

async def _resolve_plan(intent: str, slots: dict, user_query: str):
    """Planning: 启发式优先, 兜底 LLM"""
    from schemas import Plan as SchemaPlan

    try:
        from plan_engine import should_skip_planning_llm, planning_agent
        heuristic = should_skip_planning_llm([intent], slots)
        if heuristic is not None:
            return SchemaPlan(
                primary_intent=heuristic.primary_intent,
                required_agents=list(heuristic.required_agents),
                skip_agents=list(heuristic.skip_agents),
                skip_reason=heuristic.skip_reason,
                steps=[{
                    "step_id": s.step_id, "description": s.description,
                    "agent_name": s.agent_name, "depends_on": s.depends_on,
                } for s in heuristic.steps],
                confidence=heuristic.confidence,
            )

        engine_plan = await planning_agent(user_query, [intent], slots)
        return SchemaPlan(
            primary_intent=engine_plan.primary_intent,
            required_agents=list(engine_plan.required_agents),
            skip_agents=list(engine_plan.skip_agents),
            skip_reason=engine_plan.skip_reason or engine_plan.reason,
            steps=[{
                "step_id": s.step_id, "description": s.description,
                "agent_name": s.agent_name, "depends_on": s.depends_on,
            } for s in engine_plan.steps],
            confidence=engine_plan.confidence,
        )
    except Exception as e:
        logger.warning("Planning 失败，兜底全量 Agent: %s", e)
        return SchemaPlan(
            primary_intent=intent,
            required_agents=["MarketAgent", "ProfitAgent", "SupplyRiskAgent", "ReviewInsightAgent"],
            skip_agents=[],
            skip_reason="Planning 失败，兜底全量 Agent 以确保报告完整",
            confidence=0.3,
        )


def _build_constraints(slots: dict, intent: str) -> Any:
    from schemas import Constraints
    return Constraints(
        category=slots.get("category"),
        price_min=slots.get("price_min"),
        price_max=slots.get("price_max"),
        season=slots.get("season"),
        preferences=slots.get("preferences", []),
    )


def _query_candidates(constraints, top_k: int) -> list[dict]:
    from selection_service import query_candidate_products
    return query_candidate_products(constraints, top_k)


def _product_summary(product, completed_count: int, total: int) -> str:
    from selection_service import AGENT_LABELS
    recommendation = {
        "recommend": "建议选品",
        "neutral": "谨慎观察",
        "not_recommend": "暂不推荐",
    }.get(product.recommendation, product.recommendation)
    highlights = "；".join(product.highlights[:2]) if product.highlights else "暂无明确亮点"
    risks = "；".join(product.risks[:1]) if product.risks else "暂无明显风险"
    return (
        f"### 商品 {completed_count}/{total}：{product.product_name}\n"
        f"- 综合评分：{product.final_score}\n"
        f"- 选品建议：{recommendation}\n"
        f"- 主要亮点：{highlights}\n"
        f"- 风险提示：{risks}\n\n"
    )


def _split_text(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]
