from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from create_logger import get_logger
from schemas import Constraints, Plan, ProductAnalysisResult, SelectionReport, UserIntent

logger = get_logger("langgraph_selection_workflow")


class SelectionWorkflowState(TypedDict, total=False):
    request_id: str
    user_query: str
    top_k: int
    context: dict[str, Any]

    intent: str
    slots: dict[str, Any]
    user_intent: UserIntent
    plan: Plan
    agents: dict[str, str]
    constraints: Constraints
    candidates: list[dict[str, Any]]
    products_to_analyze: list[dict[str, Any]]
    products: list[ProductAnalysisResult]
    final_report: str
    report: SelectionReport

    status: str
    skip_reason: str
    validation_errors: list[str]
    agents_used: list[str]
    error: str


async def run_selection_graph(
    user_query: str,
    top_k: int = 5,
    pre_slots: dict | None = None,
    pre_intent: str | None = None,
    pre_user_intent: UserIntent | None = None,
    context: dict | None = None,
) -> dict[str, Any]:
    graph = build_selection_graph()
    state = await graph.ainvoke(
        _initial_state(
            user_query=user_query,
            top_k=top_k,
            pre_slots=pre_slots,
            pre_intent=pre_intent,
            pre_user_intent=pre_user_intent,
            context=context,
        )
    )
    return _result_from_state(state)


async def stream_selection_graph(
    user_query: str,
    top_k: int,
    pre_intent: str,
    pre_slots: dict,
    pre_user_intent: UserIntent | None,
    context: dict | None = None,
) -> AsyncGenerator[dict, None]:
    graph = build_selection_graph()
    initial = _initial_state(
        user_query=user_query,
        top_k=top_k,
        pre_slots=pre_slots,
        pre_intent=pre_intent,
        pre_user_intent=pre_user_intent,
        context=context,
    )

    latest: SelectionWorkflowState = dict(initial)
    yielded_products = False
    final_report = ""
    terminal_text_only = False

    async for update in graph.astream(initial, stream_mode="updates"):
        if not isinstance(update, dict):
            continue

        node_name, node_state = next(iter(update.items()))
        if not isinstance(node_state, dict):
            continue

        latest.update(node_state)

        if node_name == "build_plan":
            plan = latest.get("plan")
            if plan and plan.required_agents:
                skip = f" (跳过: {', '.join(plan.skip_agents)})" if plan.skip_agents else ""
                yield {
                    "event": "delta",
                    "data": {
                        "content": f"已生成 LangGraph 执行计划: {', '.join(plan.required_agents)}{skip}\n{plan.skip_reason}\n\n"
                    },
                }

        elif node_name == "select_agents":
            agents = latest.get("agents", {})
            if agents:
                yield {
                    "event": "delta",
                    "data": {"content": f"已选择 A2A Agent: {', '.join(agents.keys())}\n\n"},
                }

        elif node_name == "query_candidates":
            candidates = latest.get("products_to_analyze", [])
            if candidates:
                names = "、".join(p.get("product_name", "") for p in candidates)
                yield {
                    "event": "delta",
                    "data": {"content": f"候选商品筛选完成，进入并行分析: {names}\n\n"},
                }

        elif node_name == "validate_slots" and latest.get("validation_errors"):
            terminal_text_only = True
            yield {
                "event": "follow_up",
                "data": {
                    "question": "\n".join(latest["validation_errors"]),
                    "options": [],
                    "missing_slots": [],
                    "agents": list(latest.get("agents", {}).keys()),
                },
            }

        elif node_name == "dispatch_agents":
            products = latest.get("products", [])
            if products:
                yielded_products = True
                yield {"event": "products", "data": {"products": [p.model_dump() for p in products]}}
                yield {
                    "event": "delta",
                    "data": {"content": _products_delta(products, latest.get("top_k", top_k))},
                }

        elif node_name == "rank_products":
            products = latest.get("products", [])
            if products and not yielded_products:
                yielded_products = True
                yield {"event": "products", "data": {"products": [p.model_dump() for p in products]}}

        elif node_name == "generate_report":
            final_report = latest.get("final_report", "")
            if final_report:
                yield {"event": "delta", "data": {"content": "综合分析完成，正在生成选品报告...\n\n"}}

        elif node_name in {"skip_report", "no_candidates_report", "validation_report"}:
            terminal_text_only = True
            report = latest.get("report")
            content = report.final_report if report else latest.get("skip_reason", "")
            if content:
                yield {"event": "delta", "data": {"content": content}}

    products = latest.get("products", [])
    if products:
        yield {"event": "products", "data": {"products": [p.model_dump() for p in products]}}

    report = latest.get("report")
    if report and report.final_report:
        final_report = report.final_report

    if terminal_text_only:
        message_type = "slot_prompt" if latest.get("status") == "need_more_info" else "text"
        yield {
            "event": "done",
            "data": {"message_type": message_type, "request_id": latest.get("request_id", "")},
        }
        return

    if final_report:
        yield {"event": "report_start", "data": {"message_type": "report_card"}}
        for chunk in _split_text(final_report, 80):
            yield {"event": "report_delta", "data": {"content": chunk}}
            await asyncio.sleep(0.03)
        yield {
            "event": "done",
            "data": {"message_type": "report_card", "request_id": latest.get("request_id", "")},
        }
    else:
        yield {"event": "done", "data": {"message_type": "text", "request_id": latest.get("request_id", "")}}


def build_selection_graph():
    workflow = StateGraph(SelectionWorkflowState)

    workflow.add_node("recognize_intent", _recognize_intent)
    workflow.add_node("build_plan", _build_plan)
    workflow.add_node("skip_report", _skip_report)
    workflow.add_node("select_agents", _select_agents)
    workflow.add_node("query_candidates", _query_candidates)
    workflow.add_node("no_candidates_report", _no_candidates_report)
    workflow.add_node("validate_slots", _validate_slots)
    workflow.add_node("validation_report", _validation_report)
    workflow.add_node("dispatch_agents", _dispatch_agents)
    workflow.add_node("rank_products", _rank_products)
    workflow.add_node("generate_report", _generate_report)
    workflow.add_node("persist_report", _persist_report)
    workflow.add_node("finalize_report", _finalize_report)

    workflow.add_edge(START, "recognize_intent")
    workflow.add_edge("recognize_intent", "build_plan")
    workflow.add_conditional_edges(
        "build_plan",
        _route_after_plan,
        {"skip": "skip_report", "continue": "select_agents"},
    )
    workflow.add_edge("skip_report", END)
    workflow.add_edge("select_agents", "query_candidates")
    workflow.add_conditional_edges(
        "query_candidates",
        _route_after_candidates,
        {"empty": "no_candidates_report", "continue": "validate_slots"},
    )
    workflow.add_edge("no_candidates_report", END)
    workflow.add_conditional_edges(
        "validate_slots",
        _route_after_validation,
        {"invalid": "validation_report", "continue": "dispatch_agents"},
    )
    workflow.add_edge("validation_report", END)
    workflow.add_edge("dispatch_agents", "rank_products")
    workflow.add_edge("rank_products", "generate_report")
    workflow.add_edge("generate_report", "persist_report")
    workflow.add_edge("persist_report", "finalize_report")
    workflow.add_edge("finalize_report", END)

    return workflow.compile()


def _initial_state(
    user_query: str,
    top_k: int,
    pre_slots: dict | None,
    pre_intent: str | None,
    pre_user_intent: UserIntent | None,
    context: dict | None,
) -> SelectionWorkflowState:
    state: SelectionWorkflowState = {
        "request_id": f"req-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}",
        "user_query": user_query,
        "top_k": top_k,
        "context": context or {},
        "slots": pre_slots or {},
    }
    if pre_intent:
        state["intent"] = pre_intent
    if pre_user_intent:
        state["user_intent"] = pre_user_intent
    return state


async def _recognize_intent(state: SelectionWorkflowState) -> dict[str, Any]:
    user_query = state["user_query"]

    if state.get("intent"):
        intent = state["intent"]
        slots = state.get("slots", {})
    else:
        from intent_service import IntentClassifier

        result = IntentClassifier.classify(user_query)
        intent = result.intent
        slots = state.get("slots") or result.slots

    if state.get("user_intent"):
        user_intent = state["user_intent"]
    else:
        try:
            from user_intent_service import UserIntentRecognizer

            user_intent = UserIntentRecognizer.recognize(user_query)
        except Exception as exc:
            logger.warning("User intent recognition failed, fallback to default: %s", exc)
            user_intent = UserIntent()

    return {"intent": intent, "slots": slots, "user_intent": user_intent}


async def _build_plan(state: SelectionWorkflowState) -> dict[str, Any]:
    intent = state.get("intent", "product_selection")
    slots = state.get("slots", {})
    user_query = state["user_query"]

    try:
        from plan_engine import planning_agent, should_skip_planning_llm

        heuristic = should_skip_planning_llm([intent], slots)
        if heuristic is not None:
            plan = Plan(
                primary_intent=heuristic.primary_intent,
                required_agents=list(heuristic.required_agents),
                skip_agents=list(heuristic.skip_agents),
                skip_reason=heuristic.skip_reason,
                steps=[
                    {
                        "step_id": step.step_id,
                        "description": step.description,
                        "agent_name": step.agent_name,
                        "depends_on": step.depends_on,
                    }
                    for step in heuristic.steps
                ],
                confidence=heuristic.confidence,
            )
        else:
            engine_plan = await planning_agent(user_query, [intent], slots, state.get("context"))
            plan = Plan(
                primary_intent=engine_plan.primary_intent,
                required_agents=list(engine_plan.required_agents),
                skip_agents=list(engine_plan.skip_agents),
                skip_reason=engine_plan.skip_reason or engine_plan.reason,
                steps=[
                    {
                        "step_id": step.step_id,
                        "description": step.description,
                        "agent_name": step.agent_name,
                        "depends_on": step.depends_on,
                    }
                    for step in engine_plan.steps
                ],
                confidence=engine_plan.confidence,
            )
    except Exception as exc:
        logger.warning("Planning failed, fallback to all agents: %s", exc)
        plan = Plan(
            primary_intent=intent,
            required_agents=["MarketAgent", "ProfitAgent", "SupplyRiskAgent", "ReviewInsightAgent"],
            skip_agents=[],
            skip_reason="Planning failed, fallback to the full A2A agent set.",
            confidence=0.3,
        )

    return {"plan": plan}


def _route_after_plan(state: SelectionWorkflowState) -> Literal["skip", "continue"]:
    plan = state.get("plan")
    if not plan or not plan.required_agents:
        return "skip"
    return "continue"


async def _skip_report(state: SelectionWorkflowState) -> dict[str, Any]:
    plan = state.get("plan")
    final_report = (plan.skip_reason if plan else "") or "当前请求不需要进入 A2A 选品分析流程。"
    return {
        "status": "skipped",
        "final_report": final_report,
        "report": _build_report(state, products=[], final_report=final_report),
    }


async def _select_agents(state: SelectionWorkflowState) -> dict[str, Any]:
    from agent_selector import AgentSelector

    selected = AgentSelector.select(
        plan=state.get("plan"),
        user_intent=state.get("user_intent"),
        slots=state.get("slots", {}),
    )
    agents = {name: cfg.url for name, cfg in selected.items()}
    logger.info("[%s] LangGraph selected agents: %s", state["request_id"], list(agents.keys()))
    return {"agents": agents, "agents_used": list(agents.keys())}


async def _query_candidates(state: SelectionWorkflowState) -> dict[str, Any]:
    from selection_service import query_candidate_products

    slots = state.get("slots", {})
    constraints = Constraints(
        category=slots.get("category"),
        price_min=slots.get("price_min"),
        price_max=slots.get("price_max"),
        season=slots.get("season"),
        preferences=slots.get("preferences", []),
    )
    top_k = state.get("top_k", 5)
    candidates = query_candidate_products(constraints, min(top_k * 3, 20))
    products_to_analyze = candidates[:top_k]

    return {
        "constraints": constraints,
        "candidates": candidates,
        "products_to_analyze": products_to_analyze,
    }


def _route_after_candidates(state: SelectionWorkflowState) -> Literal["empty", "continue"]:
    return "continue" if state.get("products_to_analyze") else "empty"


async def _no_candidates_report(state: SelectionWorkflowState) -> dict[str, Any]:
    final_report = "未找到符合条件的商品信息，可以更换类目、季节或价格范围后重新查询。"
    return {
        "status": "no_candidates",
        "final_report": final_report,
        "report": _build_report(state, products=[], final_report=final_report),
    }


async def _validate_slots(state: SelectionWorkflowState) -> dict[str, Any]:
    from slot_manager import AgentSlotValidator

    agents = state.get("agents", {})
    candidates = state.get("products_to_analyze", [])
    first_product = candidates[0] if candidates else {}
    validations = AgentSlotValidator.validate_all(
        list(agents.keys()),
        state.get("slots", {}),
        product_id=first_product.get("product_id"),
    )
    failed = [item for item in validations if not item.ready]
    return {"validation_errors": [item.question for item in failed]}


def _route_after_validation(state: SelectionWorkflowState) -> Literal["invalid", "continue"]:
    return "invalid" if state.get("validation_errors") else "continue"


async def _validation_report(state: SelectionWorkflowState) -> dict[str, Any]:
    final_report = "需要补充以下信息后才能继续分析:\n" + "\n".join(state.get("validation_errors", []))
    return {
        "status": "need_more_info",
        "final_report": final_report,
        "report": _build_report(state, products=[], final_report=final_report),
    }


async def _dispatch_agents(state: SelectionWorkflowState) -> dict[str, Any]:
    from agent_dispatcher import AGENT_SEMAPHORE, AGENT_TIMEOUTS, DEFAULT_AGENT_TIMEOUT, clear_mcp_cache
    from selection_service import analyze_single_product

    agents = state.get("agents", {})
    products_to_analyze = state.get("products_to_analyze", [])
    constraints = state.get("constraints", Constraints())
    user_query = state["user_query"]

    clear_mcp_cache()
    timeout = max((AGENT_TIMEOUTS.get(name, DEFAULT_AGENT_TIMEOUT) for name in agents), default=DEFAULT_AGENT_TIMEOUT)

    async def analyze_one(product: dict[str, Any]):
        async with AGENT_SEMAPHORE:
            return await asyncio.wait_for(
                analyze_single_product(product, constraints, user_query, agents=agents),
                timeout=timeout,
            )

    started = time.time()
    raw_results = await asyncio.gather(
        *(analyze_one(product) for product in products_to_analyze),
        return_exceptions=True,
    )

    products: list[ProductAnalysisResult] = []
    for result in raw_results:
        if isinstance(result, ProductAnalysisResult):
            products.append(result)
        else:
            logger.error("[%s] Product analysis failed in LangGraph dispatch: %s", state["request_id"], result)

    logger.info(
        "[%s] LangGraph dispatch completed: products=%d elapsed=%.1fs",
        state["request_id"],
        len(products),
        time.time() - started,
    )
    return {"products": products}


async def _rank_products(state: SelectionWorkflowState) -> dict[str, Any]:
    top_k = state.get("top_k", 5)
    products = list(state.get("products", []))
    products.sort(key=lambda item: item.final_score, reverse=True)
    products = products[:top_k]
    for index, product in enumerate(products, start=1):
        product.rank = index
    return {"products": products}


async def _generate_report(state: SelectionWorkflowState) -> dict[str, Any]:
    from selection_service import generate_report

    products = state.get("products", [])
    final_report = await generate_report(state["user_query"], products)
    return {"final_report": final_report}


async def _persist_report(state: SelectionWorkflowState) -> dict[str, Any]:
    from selection_service import save_agent_logs, save_selection_report

    products = state.get("products", [])
    final_report = state.get("final_report", "")
    constraints = state.get("constraints", Constraints())
    save_selection_report(state["request_id"], state["user_query"], constraints, products, final_report)
    save_agent_logs(state["request_id"], products)
    return {}


async def _finalize_report(state: SelectionWorkflowState) -> dict[str, Any]:
    report = _build_report(state, state.get("products", []), state.get("final_report", ""))
    return {"status": "completed", "report": report}


def _build_report(
    state: SelectionWorkflowState,
    products: list[ProductAnalysisResult],
    final_report: str,
) -> SelectionReport:
    return SelectionReport(
        request_id=state["request_id"],
        query=state["user_query"],
        constraints=state.get("constraints", Constraints()),
        products=products,
        final_report=final_report,
        created_at=datetime.now(),
    )


def _result_from_state(state: SelectionWorkflowState) -> dict[str, Any]:
    report = state.get("report")
    if report is None:
        report = _build_report(state, state.get("products", []), state.get("final_report", ""))
    return {
        "request_id": state.get("request_id", report.request_id),
        "report": report,
        "plan": state.get("plan"),
        "agents_used": state.get("agents_used", list(state.get("agents", {}).keys())),
        "workflow_state": state,
    }


def _products_delta(products: list[ProductAnalysisResult], top_k: int) -> str:
    lines = [f"已完成 {len(products)} 个商品的 A2A 并行分析，当前最多返回 Top {top_k}。"]
    for product in products:
        lines.append(f"- {product.product_name}: 综合得分 {product.final_score}, 建议 {product.recommendation}")
    return "\n".join(lines) + "\n\n"


def _split_text(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]
