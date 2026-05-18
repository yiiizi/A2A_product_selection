from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from create_logger import get_logger
from memory import ConversationMemory
from schemas import ChatMessage, ChatRequest, ChatResponse, ChatResult, Constraints
from agent_selector import AgentSelector
from schemas import Plan
from selection_service import (
    analyze_single_product,
    generate_report,
    query_candidate_products,
    save_agent_logs,
    save_selection_report,
)
from session_service import SessionManager

logger = get_logger("session_orchestrator")

# 全局记忆实例（每个会话独立，key=session_id）
_session_memories: dict[str, ConversationMemory] = {}
_CATEGORY_PREF_KEYS = ["家居小电器", "厨房用品", "宠物用品", "美妆个护", "运动户外"]


def _get_memory(session_id: str) -> ConversationMemory:
    """获取或创建会话对应的 Memory 实例"""
    if session_id not in _session_memories:
        _session_memories[session_id] = ConversationMemory(short_term_limit=10)
    return _session_memories[session_id]


async def _auto_learn_preferences(memory: ConversationMemory, message: str, slots: dict):
    """自动从用户行为中学习偏好"""
    # 从槽位学习偏好
    if slots.get("category") in _CATEGORY_PREF_KEYS:
        memory.user_preferences["preferred_category"] = slots["category"]
    if slots.get("price_min") is not None and slots.get("price_max") is not None:
        memory.user_preferences["price_range"] = f"{slots['price_min']}-{slots['price_max']}"
    if slots.get("season"):
        memory.user_preferences["preferred_season"] = slots["season"]
    # 持久化
    memory.save_preferences_to_db()


async def _llm_recognize_intent(
    message: str,
    memory: ConversationMemory,
) -> dict | None:
    """LLM 意图识别 + 槽位抽取（主路径）。失败返回 None 走正则兜底。"""
    from config import API_KEY, BASE_URL, LLM_MODEL, LLM_TEMPERATURE, MOCK_LLM
    from openai import OpenAI
    from prompts import INTENT_SLOT_RECOGNIZE_V2

    if MOCK_LLM or not API_KEY:
        return None

    prompt = INTENT_SLOT_RECOGNIZE_V2.format(
        conversation_history=memory.get_short_term_text(),
        task_context=json.dumps(memory.current_task, ensure_ascii=False),
        user_preferences=memory.get_preference_text(),
        query=message,
    )

    try:
        client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        completion = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是电商选品对话助手。只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=LLM_TEMPERATURE,
        )
        text = completion.choices[0].message.content or ""
    except Exception as e:
        logger.warning("LLM 意图识别失败，降级为正则兜底: %s", e)
        return None

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
                return None
        else:
            return None

    return data

CATEGORY_OPTIONS = ["家居小电器", "厨房用品", "宠物用品", "美妆个护", "运动户外"]

CATEGORY_FUZZY_MAP = {
    # 美妆个护
    "护肤品": "美妆个护", "化妆品": "美妆个护", "彩妆": "美妆个护", "面膜": "美妆个护",
    "护肤": "美妆个护", "美妆": "美妆个护", "个护": "美妆个护", "口红": "美妆个护",
    # 家居小电器
    "家电": "家居小电器", "小家电": "家居小电器", "电器": "家居小电器",
    "风扇": "家居小电器", "台灯": "家居小电器", "吸尘器": "家居小电器",
    # 厨房用品
    "厨具": "厨房用品", "厨房": "厨房用品", "锅": "厨房用品", "榨汁": "厨房用品",
    # 宠物用品
    "猫": "宠物用品", "狗": "宠物用品", "宠物": "宠物用品",
    # 运动户外
    "运动": "运动户外", "户外": "运动户外", "健身": "运动户外", "瑜伽": "运动户外",
}


def _normalize_category(cat: str | None) -> str | None:
    """将用户输入的自由类目映射到数据库类目"""
    if not cat:
        return None
    if cat in CATEGORY_OPTIONS:
        return cat
    for fuzzy_key, db_cat in CATEGORY_FUZZY_MAP.items():
        if fuzzy_key in cat:
            return db_cat
    return cat  # 保持原值，后续 DB 查不到会提示
UNSUPPORTED_CATEGORY_HINTS = [
    "数码",
    "数码配件",
    "手机配件",
    "电脑配件",
    "充电器",
    "耳机",
    "服饰",
    "女装",
    "男装",
    "鞋帽",
    "母婴",
    "儿童",
    "婴儿",
    "家具",
]

SELECTION_KEYWORDS = [
    "选品",
    "选",
    "推荐",
    "分析",
    "商品",
    "产品",
    "爆品",
    "类目",
    "电器",
    "家电",
    "小家电",
    "厨房电器",
    "Amazon",
    "amazon",
    "亚马逊",
    "有哪些类目",
    "有什么类目",
    "类目有哪些",
    "可选类目",
    "有哪些目录",
    "有什么目录",
    "目录有哪些",
    "可选目录",
] + UNSUPPORTED_CATEGORY_HINTS

REQUIRED_SELECTION_SLOTS = ["category", "season", "price_min", "price_max"]
ANY_PRICE_MAX = 999999.0


def _event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def handle_message(request: ChatRequest) -> ChatResponse:
    content = ""
    products: list[dict] = []
    message_type = "text"
    follow_up = None

    async for item in stream_message(request):
        event = item["event"]
        data = item["data"]
        if event == "delta":
            content += data.get("content", "")
        elif event == "follow_up":
            content = data.get("question", "")
            follow_up = data
            message_type = "slot_prompt"
        elif event == "report_start":
            content = ""
            message_type = "report_card"
        elif event == "report_delta":
            content += data.get("content", "")
        elif event == "products":
            products = data.get("products", [])

    return ChatResponse(
        session_id=request.session_id,
        message=ChatMessage(role="assistant", content=content, message_type=message_type),
        follow_up=follow_up,
        result=(
            ChatResult(
                result_type="selection_report",
                products=products,
                report=content,
                quick_actions=["查看商品详情", "调整价格区间", "重新选品"],
            )
            if products
            else None
        ),
    )


async def stream_message(request: ChatRequest) -> AsyncGenerator[dict, None]:
    session = SessionManager.get_or_create_session(request.session_id)
    SessionManager.add_message(
        session_id=request.session_id,
        role="user",
        content=request.message,
        message_type="text",
    )

    context = _load_context(session)
    memory = _get_memory(request.session_id)

    # 尝试 LLM 意图识别
    llm_intent = await _llm_recognize_intent(request.message, memory)
    # 如果上下文显示正在填槽中，且 LLM 返回 general_chat，强制当作 slot_reply
    if llm_intent and llm_intent.get("intent") == "general_chat" and context.get("slots_missing"):
        llm_intent["intent"] = "slot_reply"
    if llm_intent:
        intent = llm_intent.get("intent", "general_chat")
        follow_up_msg = llm_intent.get("follow_up_message", "")
        slots = llm_intent.get("slots", {})
        missing = llm_intent.get("slots_missing", [])
        # 类目模糊映射
        if slots.get("category"):
            slots["category"] = _normalize_category(slots["category"])

        if intent == "general_chat" and not follow_up_msg:
            content = _generic_reply(request.message)
            for chunk in _split_text(content, 18):
                yield {"event": "delta", "data": {"content": chunk}}
                await asyncio.sleep(0.02)
            SessionManager.add_message(
                session_id=request.session_id,
                role="assistant",
                content=content,
                message_type="text",
            )
            yield {"event": "done", "data": {"message_type": "text"}}
            return

        # slot_reply: 从用户回复提取槽位，合并到上下文
        if intent == "slot_reply":
            prev_slots = context.get("slots", {})
            for k, v in slots.items():
                if v is not None and v != "" and v != []:
                    prev_slots[k] = v
            # 重新计算缺失
            new_missing = [s for s in ["category", "season", "price_min", "price_max"] if not prev_slots.get(s)]
            intent = context.get("intent", "product_selection")
            slots = prev_slots
            missing = new_missing
            memory.update_task_context({"intent": intent, "slots": slots, "slots_missing": missing})

        # ★ 步骤1: 用户意图识别（业务场景/角色/动机）
        user_intent = None
        try:
            from user_intent_service import UserIntentRecognizer
            history = SessionManager.get_history(request.session_id, limit=10)
            user_intent = UserIntentRecognizer.recognize(request.message, history)
            logger.info("用户意图: exp=%s goal=%s scale=%s", user_intent.experience_level, user_intent.goal, user_intent.scale)
        except Exception as e:
            logger.warning("用户意图识别失败，使用默认值: %s", e)

        # ★ 先判断槽位是否齐全，再决定追问还是执行
        if intent == "product_selection" and not missing:
            memory.add_message("user", request.message)
            memory.update_task_context({"intent": intent, "slots": slots})

            context["intent"] = intent
            context["slots"] = slots
            context["slots_missing"] = []
            context["follow_up_count"] = 0
            SessionManager.update_context(request.session_id, context)

            await _auto_learn_preferences(memory, request.message, slots)
            memory.add_query(intent, request.message)

            # ★ 步骤2: Planning (启发式优先, 省 LLM 调用)
            selection_plan: Plan | None = None
            try:
                from plan_engine import should_skip_planning_llm, planning_agent

                # 先尝试启发式 (省 1 次 LLM)
                heuristic = should_skip_planning_llm([intent], slots)
                if heuristic is not None:
                    logger.info("启发式 Plan: agents=%s skip=%s", heuristic.required_agents, heuristic.skip_agents)
                    selection_plan = Plan(
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
                    if heuristic.skip_reason:
                        yield {"event": "delta", "data": {
                            "content": f"任务分析: {heuristic.skip_reason}\n\n"
                        }}
                else:
                    # 启发式无法判断 → 调用 LLM Planning
                    logger.info("触发 LLM Planning Agent")
                    engine_plan = await planning_agent(request.message, [intent], slots, context)
                    selection_plan = Plan(
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
                    if engine_plan.steps:
                        skip_msg = f" (跳过: {', '.join(engine_plan.skip_agents)})" if engine_plan.skip_agents else ""
                        content = f"任务规划完成（{len(engine_plan.steps)} 步）{skip_msg}：{engine_plan.reason}\n\n"
                        for chunk in _split_text(content, 30):
                            yield {"event": "delta", "data": {"content": chunk}}
                            await asyncio.sleep(0.02)
            except Exception as e:
                logger.warning("Planning 失败，兜底: %s", e)

            async for item in _stream_selection(request, session, slots, user_intent=user_intent, plan=selection_plan):
                yield item
            return

        if follow_up_msg and missing:
            context["intent"] = intent
            context["slots"] = slots
            context["slots_missing"] = missing
            context["follow_up_count"] = context.get("follow_up_count", 0) + 1
            SessionManager.update_context(request.session_id, context)

            memory.add_message("user", request.message)
            memory.add_message("assistant", follow_up_msg)
            memory.update_task_context({
                "intent": intent, "slots": slots, "slots_missing": missing,
                "last_system_question": follow_up_msg,
            })

            yield {"event": "follow_up", "data": {
                "question": follow_up_msg,
                "options": [],
                "missing_slots": missing,
            }}
            yield {"event": "done", "data": {"message_type": "slot_prompt"}}
            return

        # 意图路由：非选品意图
        if intent == "report_lookup":
            memory.add_message("user", request.message)
            async for item in _stream_report_lookup(request, session):
                yield item
            return

        if intent == "product_compare":
            memory.add_message("user", request.message)
            async for item in _stream_product_compare(request, session, slots):
                yield item
            return

        if intent == "supply_inquiry":
            memory.add_message("user", request.message)
            async for item in _stream_supply_inquiry(request, session, slots):
                yield item
            return

        # LLM 识别了非选品意图 → 走正常正则路径（兼容）
        context["intent"] = intent
        context["slots"] = slots

    if not _is_selection_request(request.message, context):
        content = _generic_reply(request.message)
        for chunk in _split_text(content, 18):
            yield {"event": "delta", "data": {"content": chunk}}
            await asyncio.sleep(0.02)
        SessionManager.add_message(
            session_id=request.session_id,
            role="assistant",
            content=content,
            message_type="text",
        )
        yield {"event": "done", "data": {"message_type": "text"}}
        return

    context["intent"] = "product_selection"
    if _is_category_catalog_question(request.message):
        existing_slots = dict(context.get("slots", {}))
        existing_slots.pop("category", None)
        context["slots"] = existing_slots
        context["awaiting_slot"] = "category"

    extracted = _extract_slots(request.message, context)
    if _should_return_unsupported_category(request.message, context, extracted):
        context["awaiting_slot"] = "category"
        context["slots_missing"] = REQUIRED_SELECTION_SLOTS
        SessionManager.update_context(request.session_id, context)
        content = _unsupported_category_reply()
        for chunk in _split_text(content, 18):
            yield {"event": "delta", "data": {"content": chunk}}
            await asyncio.sleep(0.02)
        SessionManager.add_message(
            session_id=request.session_id,
            role="assistant",
            content=content,
            message_type="text",
        )
        yield {"event": "done", "data": {"message_type": "text"}}
        return

    slots = _merge_slots(context.get("slots", {}), extracted)
    if slots.get("category"):
        slots["category"] = _normalize_category(slots["category"])
    missing = _missing_slots(slots)
    context["slots"] = slots
    context["slots_missing"] = missing

    if missing:
        follow_up = _build_follow_up(missing, slots)
        context["awaiting_slot"] = missing[0]
        context["follow_up_count"] = context.get("follow_up_count", 0) + 1
        SessionManager.update_context(request.session_id, context)
        SessionManager.add_message(
            session_id=request.session_id,
            role="assistant",
            content=follow_up["question"],
            message_type="slot_prompt",
            metadata={"follow_up": follow_up},
        )
        # ★ 正则路径也写入 memory，确保下轮有上下文
        regex_mem = _get_memory(request.session_id)
        regex_mem.add_message("user", request.message)
        regex_mem.add_message("assistant", follow_up["question"])
        regex_mem.update_task_context({
            "intent": "product_selection", "slots": slots, "slots_missing": missing,
        })
        yield {"event": "follow_up", "data": follow_up}
        yield {"event": "done", "data": {"message_type": "slot_prompt"}}
        return

    context["awaiting_slot"] = ""
    context["slots_missing"] = []
    context["follow_up_count"] = 0
    SessionManager.update_context(request.session_id, context)

    # 自动学习用户偏好
    memory = _get_memory(request.session_id)
    memory.add_message("user", request.message)
    await _auto_learn_preferences(memory, request.message, slots)
    memory.add_query("product_selection", request.message)

    async for item in _stream_selection(request, session, slots):
        yield item


async def _stream_selection(request: ChatRequest, session: dict, slots: dict, user_intent=None, plan: Plan | None = None) -> AsyncGenerator[dict, None]:
    top_k = _extract_top_k(request.message)
    request_id = f"req-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
    start_time = time.time()
    query = _compose_selection_query(request.message, slots)

    # ★ 根据 Plan + 用户意图动态选择 Agent 组合
    agents = AgentSelector.select(plan=plan, user_intent=user_intent, slots=slots)
    agent_names = "、".join(agents.keys())
    logger.info("开始选品 session=%s top_k=%s slots=%s agents=%s", request.session_id, top_k, slots, list(agents.keys()))
    yield {
        "event": "delta",
        "data": {"content": f"槽位已补齐：{_slot_brief(slots)}\n\n正在检索候选商品，并启动 {len(agents)} 个 A2A Agent（{agent_names}）并行分析。\n\n"},
    }

    constraints = Constraints(
        category=slots.get("category"),
        price_min=slots.get("price_min"),
        price_max=None if slots.get("price_max") == ANY_PRICE_MAX else slots.get("price_max"),
        season=slots.get("season"),
        preferences=slots.get("preferences", []),
    )

    try:
        candidates = await asyncio.to_thread(query_candidate_products, constraints, min(top_k * 3, 20))
    except Exception as exc:
        logger.exception("候选商品检索失败")
        yield {"event": "error", "data": {"message": f"候选商品检索失败：{exc}"}}
        return

    if not candidates:
        content = "没有找到满足当前条件的候选商品，可以放宽类目或价格区间后再试。"
        yield {"event": "delta", "data": {"content": content}}
        SessionManager.add_message(
            session_id=request.session_id,
            role="assistant",
            content=content,
            message_type="text",
        )
        yield {"event": "done", "data": {"message_type": "text"}}
        return

    products_to_analyze = candidates[: min(3, top_k)]

    # ★ 阶段6: Agent 专属槽位校验 (DB 自动填充 + 缺失追问)
    if products_to_analyze:
        first_pid = products_to_analyze[0].get("product_id")
        from slot_manager import AgentSlotValidator
        validations = AgentSlotValidator.validate_all(
            list(agents.keys()), slots, product_id=first_pid,
        )
        failed = [v for v in validations if not v.ready]
        if failed:
            # 有 Agent 缺失必填槽位 → 追问用户
            questions = [v.question for v in failed]
            missing_all = [slot for v in failed for slot in v.missing_required]
            yield {"event": "follow_up", "data": {
                "question": "\n".join(questions),
                "options": [],
                "missing_slots": missing_all,
                "agents": [v.name for v in failed],
            }}
            logger.info("Agent 槽位不足，追问: %s", [v.name for v in failed])
            return

    names = "、".join(p.get("product_name", "") for p in products_to_analyze)
    yield {
        "event": "delta",
        "data": {
            "content": (
                f"已筛出 {len(products_to_analyze)} 个候选商品：{names}\n\n"
                "A2A Agent 将并行评估市场、利润、供应和口碑。完成一个商品就先输出一个商品结果。\n\n"
            )
        },
    }

    # ★ 阶段7: Agent 调度 (MCP 缓存清理 + 信号量 + 超时)
    from agent_dispatcher import clear_mcp_cache, AGENT_SEMAPHORE, AGENT_TIMEOUTS, DEFAULT_AGENT_TIMEOUT
    clear_mcp_cache()

    max_timeout = max(
        (AGENT_TIMEOUTS.get(name, DEFAULT_AGENT_TIMEOUT) for name in agents.keys()),
        default=DEFAULT_AGENT_TIMEOUT,
    )

    async def _analyze_with_limit(product):
        async with AGENT_SEMAPHORE:
            return await asyncio.wait_for(
                analyze_single_product(product, constraints, query, agents=agents),
                timeout=max_timeout,
            )

    tasks = [
        asyncio.create_task(_analyze_with_limit(product))
        for product in products_to_analyze
    ]

    completed_products = []
    total = len(tasks)
    for done in asyncio.as_completed(tasks):
        try:
            product = await done
        except asyncio.TimeoutError:
            logger.warning("单商品分析超时 (%.0fs)", max_timeout)
            yield {"event": "delta", "data": {"content": f"有一个商品分析超时（{max_timeout}秒），跳过。\n\n"}}
            continue
        except Exception as exc:
            logger.exception("单商品分析失败")
            yield {"event": "delta", "data": {"content": f"有一个商品分析失败：{exc}\n\n"}}
            continue

        completed_products.append(product)
        completed_products.sort(key=lambda p: p.final_score, reverse=True)
        for idx, item in enumerate(completed_products, start=1):
            item.rank = idx

        yield {"event": "products", "data": {"products": [p.model_dump() for p in completed_products]}}
        yield {"event": "delta", "data": {"content": _product_summary(product, len(completed_products), total)}}

    if not completed_products:
        yield {"event": "error", "data": {"message": "A2A Agent 没有返回可用结果，请检查 Agent 服务和 MCP 服务。"}}
        return

    completed_products.sort(key=lambda p: p.final_score, reverse=True)
    products = completed_products[:top_k]
    for idx, product in enumerate(products, start=1):
        product.rank = idx

    yield {"event": "products", "data": {"products": [p.model_dump() for p in products]}}
    yield {"event": "delta", "data": {"content": "商品并行分析已完成，正在生成最终综合选品报告。\n\n"}}

    final_report = await generate_report(query, products)
    save_selection_report(request_id, query, constraints, products, final_report)
    save_agent_logs(request_id, products)

    latest_context = _load_context(SessionManager.get_or_create_session(request.session_id))
    latest_context["last_selection_request_id"] = request_id
    latest_context["last_product_ids"] = [p.product_id for p in products]
    SessionManager.update_context(request.session_id, latest_context)

    yield {"event": "report_start", "data": {"message_type": "report_card"}}
    for chunk in _split_text(final_report, 80):
        yield {"event": "report_delta", "data": {"content": chunk}}
        await asyncio.sleep(0.03)

    SessionManager.add_message(
        session_id=request.session_id,
        role="assistant",
        content=final_report,
        message_type="report_card",
        metadata={"request_id": request_id, "product_count": len(products)},
    )
    elapsed = time.time() - start_time
    logger.info("选品完成 session=%s request=%s %.1fs", request.session_id, request_id, elapsed)
    yield {"event": "done", "data": {"message_type": "report_card", "request_id": request_id}}


async def _stream_report_lookup(request: ChatRequest, session: dict) -> AsyncGenerator[dict, None]:
    """查询历史报告"""
    from database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        rows = db.execute(
            text("SELECT request_id, user_query, created_at FROM selection_reports ORDER BY created_at DESC LIMIT 5")
        ).fetchall()
        reports = [{"request_id": r[0], "query": r[1], "created_at": str(r[2])} for r in rows]

        content = "## 历史选品报告\n\n" if reports else "暂无历史选品报告。"
        for rp in reports:
            content += f"- [{rp['created_at']}] {rp['query'][:60]} (ID: {rp['request_id']})\n"

        for chunk in _split_text(content, 30):
            yield {"event": "delta", "data": {"content": chunk}}
            await asyncio.sleep(0.02)

        SessionManager.add_message(session_id=request.session_id, role="assistant", content=content, message_type="text")
        yield {"event": "done", "data": {"message_type": "text"}}
    finally:
        db.close()


async def _stream_product_compare(request: ChatRequest, session: dict, slots: dict) -> AsyncGenerator[dict, None]:
    """商品对比：快速分析两个商品并输出对比报告"""
    target_ids = slots.get("target_product_ids", [])
    if not target_ids or len(target_ids) < 2:
        content = "请提供至少 2 个商品名称或 ID 进行对比。例如：对比商品 101 和 104。"
        for chunk in _split_text(content, 30):
            yield {"event": "delta", "data": {"content": chunk}}
            await asyncio.sleep(0.02)
        SessionManager.add_message(session_id=request.session_id, role="assistant", content=content, message_type="text")
        yield {"event": "done", "data": {"message_type": "text"}}
        return

    constraints = Constraints(category=slots.get("category"))
    candidates = await asyncio.to_thread(query_candidate_products, constraints, 10)
    targets = [p for p in candidates if p["product_id"] in target_ids]

    if len(targets) < 2:
        content = f"未找到指定商品，请确认商品 ID 正确。当前类目候选: {[p['product_id'] for p in candidates[:5]]}"
        for chunk in _split_text(content, 30):
            yield {"event": "delta", "data": {"content": chunk}}
            await asyncio.sleep(0.02)
        yield {"event": "done", "data": {"message_type": "text"}}
        return

    yield {"event": "delta", "data": {"content": f"正在对比 {targets[0].get('product_name','')} vs {targets[1].get('product_name','')}...\n\n"}}

    plan = Plan(primary_intent="product_compare", required_agents=[], skip_agents=[])
    agents = AgentSelector.select(plan=plan, slots=slots)

    # Agent Slot 校验
    if targets:
        from slot_manager import AgentSlotValidator
        validations = AgentSlotValidator.validate_all(
            list(agents.keys()), slots, product_id=targets[0].get("product_id"),
        )
        failed = [v for v in validations if not v.ready]
        if failed:
            questions = [v.question for v in failed]
            yield {"event": "follow_up", "data": {
                "question": "\n".join(questions),
                "options": [],
                "missing_slots": [s for v in failed for s in v.missing_required],
            }}
            return

    results = []
    for product in targets[:2]:
        result = await analyze_single_product(product, constraints, request.message, agents=agents)
        results.append(result)

    content = f"""## 商品对比

| 维度 | {results[0].product_name} | {results[1].product_name} |
|------|{'-'*len(results[0].product_name)}-|{'-'*len(results[1].product_name)}-|
| 综合评分 | {results[0].final_score} | {results[1].final_score} |
| 推荐度 | {results[0].recommendation} | {results[1].recommendation} |
"""
    for chunk in _split_text(content, 60):
        yield {"event": "delta", "data": {"content": chunk}}
        await asyncio.sleep(0.03)

    SessionManager.add_message(session_id=request.session_id, role="assistant", content=content, message_type="text")
    yield {"event": "done", "data": {"message_type": "text"}}


async def _stream_supply_inquiry(request: ChatRequest, session: dict, slots: dict) -> AsyncGenerator[dict, None]:
    """供应链咨询：单独调 SupplyRiskAgent"""
    category = slots.get("category", "")
    if not category:
        content = "请提供您想了解的类目。例如：我想了解家居小电器的供应链风险。"
        for chunk in _split_text(content, 30):
            yield {"event": "delta", "data": {"content": chunk}}
        yield {"event": "done", "data": {"message_type": "text"}}
        return

    constraints = Constraints(category=category)
    candidates = await asyncio.to_thread(query_candidate_products, constraints, 3)
    if not candidates:
        yield {"event": "delta", "data": {"content": f"未找到类目「{category}」的商品。"}}
        yield {"event": "done", "data": {"message_type": "text"}}
        return

    plan = Plan(primary_intent="supply_inquiry", required_agents=[], skip_agents=[])
    agents = AgentSelector.select(plan=plan, slots=slots)

    # Agent Slot 校验
    if candidates:
        from slot_manager import AgentSlotValidator
        validations = AgentSlotValidator.validate_all(
            list(agents.keys()), slots, product_id=candidates[0].get("product_id"),
        )
        failed = [v for v in validations if not v.ready]
        if failed:
            questions = [v.question for v in failed]
            yield {"event": "follow_up", "data": {
                "question": "\n".join(questions),
                "options": [],
                "missing_slots": [s for v in failed for s in v.missing_required],
            }}
            return

    content = f"正在分析「{category}」的供应链风险...\n\n"
    yield {"event": "delta", "data": {"content": content}}

    for product in candidates[:2]:
        result = await analyze_single_product(product, constraints, request.message, agents=agents)
        sr = result.agent_results.get("SupplyRiskAgent")
        if sr and sr.status == "success":
            for chunk in _split_text(f"### {product.get('product_name','')}\n{sr.summary}\n风险等级: {sr.details.get('risk_level','?')}\n\n", 40):
                yield {"event": "delta", "data": {"content": chunk}}
                await asyncio.sleep(0.02)

    yield {"event": "delta", "data": {"content": "\n建议核实供应商资质、交期和起订量后再决策。"}}
    yield {"event": "done", "data": {"message_type": "text"}}


def _load_context(session: dict) -> dict:
    try:
        return json.loads(session.get("context_json", "{}")) if session.get("context_json") else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _is_selection_request(message: str, context: dict | None = None) -> bool:
    if (context or {}).get("intent") == "product_selection":
        return True
    lowered = message.lower()
    return any(keyword.lower() in lowered for keyword in SELECTION_KEYWORDS)


def _extract_top_k(message: str) -> int:
    match = re.search(r"(?:top|前|推荐|输出)\s*(\d+)", message, re.IGNORECASE)
    if match:
        return max(1, min(10, int(match.group(1))))
    return 5


def _generic_reply(message: str) -> str:
    if any(word in message.lower() for word in ["你好", "hi", "hello"]):
        return "你好，我可以帮你做电商选品分析。你可以直接输入类目、季节和价格区间，比如：夏季 家居小电器 100-300 元。"
    return "我主要处理电商选品相关需求。你可以告诉我想选的类目、季节、价格区间和偏好，我会先补齐槽位，再调用 A2A 多智能体分析。"


def _unsupported_category_reply() -> str:
    categories = "、".join(CATEGORY_OPTIONS)
    return f"未找到相关类目的商品信息。当前可查询的类目有：{categories}。可以换一个类目或商品再试。"


def _extract_slots(message: str, context: dict) -> dict[str, Any]:
    text = message.strip()
    slots: dict[str, Any] = {}

    category = _extract_category(text)
    if category:
        slots["category"] = _normalize_category(category)

    season = _extract_season(text)
    if season:
        slots["season"] = season

    price_min, price_max = _extract_price_range(text)
    if price_min is not None:
        slots["price_min"] = price_min
    if price_max is not None:
        slots["price_max"] = price_max

    preferences = _extract_preferences(text)
    if preferences:
        slots["preferences"] = preferences

    awaiting = context.get("awaiting_slot")
    if awaiting and awaiting not in slots:
        direct = _extract_direct_slot(awaiting, text)
        if direct:
            slots.update(direct)

    return slots


def _extract_category(text: str) -> str | None:
    if _is_category_catalog_question(text):
        return None

    rules = [
        ("厨房用品", ["厨房用品", "厨房电器", "厨房小电器", "空气炸锅", "电热水壶", "咖啡机", "厨具"]),
        ("宠物用品", ["宠物用品", "宠物", "猫", "狗"]),
        ("美妆个护", ["美妆个护", "美妆护肤", "美妆", "护肤", "个护", "彩妆"]),
        ("运动户外", ["运动户外", "运动", "户外", "健身"]),
        ("家居小电器", ["家居小电器", "家具小电器", "生活电器", "小家电", "家电", "电器"]),
    ]
    for category, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return category
    if text in CATEGORY_OPTIONS:
        return text
    return None


def _should_return_unsupported_category(message: str, context: dict, extracted: dict[str, Any]) -> bool:
    if extracted.get("category") or _is_category_catalog_question(message):
        return False

    text = message.strip()
    awaiting_category = context.get("awaiting_slot") == "category"
    has_active_selection = context.get("intent") == "product_selection"
    has_supported_signal = _extract_season(text) or _extract_price_range(text) != (None, None)

    if any(keyword in text for keyword in UNSUPPORTED_CATEGORY_HINTS):
        return True

    if awaiting_category and text and not has_supported_signal:
        return True

    if has_active_selection and any(word in text for word in ["商品", "产品", "类目", "目录"]) and not has_supported_signal:
        return True

    return False


def _is_category_catalog_question(text: str) -> bool:
    patterns = [
        "有哪些类目",
        "有什么类目",
        "类目有哪些",
        "可选类目",
        "支持哪些类目",
        "能选哪些类目",
        "有哪些目录",
        "有什么目录",
        "目录有哪些",
        "可选目录",
        "支持哪些目录",
        "能选哪些目录",
        "四个类目",
        "五个类目",
    ]
    return any(pattern in text for pattern in patterns)


def _extract_season(text: str) -> str | None:
    if any(word in text for word in ["春季", "春天", "春"]):
        return "春季"
    if any(word in text for word in ["夏季", "夏天", "夏"]):
        return "夏季"
    if any(word in text for word in ["秋季", "秋天", "秋"]):
        return "秋季"
    if any(word in text for word in ["冬季", "冬天", "冬"]):
        return "冬季"
    if any(word in text for word in ["日常", "全年", "四季", "不限季节"]):
        return "日常"
    return None


def _extract_price_range(text: str) -> tuple[float | None, float | None]:
    if "不限" in text and any(word in text for word in ["价格", "预算", "客单", "元", "价位", "无所谓"]):
        return 0.0, ANY_PRICE_MAX

    range_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|~|到|至|—)\s*(\d+(?:\.\d+)?)", text)
    if range_match:
        return float(range_match.group(1)), float(range_match.group(2))

    under_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元)?\s*(?:以内|以下|之内|内)", text)
    if under_match:
        return 0.0, float(under_match.group(1))

    above_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元)?\s*(?:以上|起|往上)", text)
    if above_match:
        return float(above_match.group(1)), ANY_PRICE_MAX

    return None, None


def _extract_preferences(text: str) -> list[str]:
    preferences = []
    rules = [
        ("高利润", ["高利润", "利润优先", "毛利高", "赚钱"]),
        ("高销量", ["高销量", "销量高", "热销", "爆品"]),
        ("低竞争", ["低竞争", "竞争小", "蓝海"]),
        ("低风险", ["低风险", "稳定", "风险低"]),
        ("Amazon", ["amazon", "Amazon", "亚马逊"]),
    ]
    for label, keywords in rules:
        if any(keyword in text for keyword in keywords):
            preferences.append(label)
    return preferences


def _extract_direct_slot(slot: str, text: str) -> dict[str, Any]:
    if slot == "category":
        category = _extract_category(text)
        return {"category": category} if category else {}
    if slot == "season":
        season = _extract_season(text)
        return {"season": season} if season else {}
    if slot in {"price_min", "price_max"}:
        if text.strip() in {"不限", "不限价格", "无所谓"}:
            return {"price_min": 0.0, "price_max": ANY_PRICE_MAX}
        price_min, price_max = _extract_price_range(text)
        result = {}
        if price_min is not None:
            result["price_min"] = price_min
        if price_max is not None:
            result["price_max"] = price_max
        nums = re.findall(r"\d+(?:\.\d+)?", text)
        if not result and nums:
            num = float(nums[0])
            if slot == "price_min":
                result["price_min"] = num
            else:
                result["price_max"] = num
        return result
    return {}


def _merge_slots(previous: dict, extracted: dict) -> dict:
    merged = dict(previous or {})
    for key, value in extracted.items():
        if value is None or value == "" or value == []:
            continue
        if key == "preferences":
            old = merged.get("preferences") or []
            merged[key] = list(dict.fromkeys([*old, *value]))
        else:
            merged[key] = value
    return merged


def _missing_slots(slots: dict) -> list[str]:
    return [key for key in REQUIRED_SELECTION_SLOTS if slots.get(key) in (None, "", [])]


def _build_follow_up(missing: list[str], slots: dict) -> dict:
    slot = missing[0]
    labels = {
        "category": "商品类目",
        "season": "季节/使用场景",
        "price_min": "最低价格",
        "price_max": "最高价格",
    }
    questions = {
        "category": "请选择要分析的商品类目，也可以直接输入类目名称。",
        "season": "这个选品需求主要面向哪个季节或场景？",
        "price_min": "还需要价格区间。请直接输入完整区间，例如 100-300 元；也可以点下面的快捷选项。",
        "price_max": "还需要最高价格。请直接输入完整区间，例如 100-300 元；也可以输入 300 以内。",
    }
    options = {
        "category": CATEGORY_OPTIONS,
        "season": ["春季", "夏季", "秋季", "冬季", "日常"],
        "price_min": ["50-150 元", "100-300 元", "200-500 元", "不限价格"],
        "price_max": ["100-300 元", "200-500 元", "500 元以内", "不限价格"],
    }
    return {
        "question": questions[slot],
        "options": options.get(slot, []),
        "missing_slots": [labels.get(item, item) for item in missing],
        "slot_key": slot,
    }


def _compose_selection_query(message: str, slots: dict) -> str:
    preferences = "、".join(slots.get("preferences") or [])
    price_max = "不限" if slots.get("price_max") == ANY_PRICE_MAX else slots.get("price_max")
    return (
        f"{message}\n"
        f"已确认槽位：类目={slots.get('category')}，季节={slots.get('season')}，"
        f"价格={slots.get('price_min')}-{price_max} 元，偏好={preferences or '无特别偏好'}。"
    )


def _slot_brief(slots: dict) -> str:
    parts = []
    if slots.get("category"):
        parts.append(f"类目={slots['category']}")
    if slots.get("season"):
        parts.append(f"季节={slots['season']}")
    if slots.get("price_min") is not None or slots.get("price_max") is not None:
        price_max = "不限" if slots.get("price_max") == ANY_PRICE_MAX else slots.get("price_max", "?")
        parts.append(f"价格={slots.get('price_min', '?')}-{price_max} 元")
    if slots.get("preferences"):
        parts.append(f"偏好={'、'.join(slots['preferences'])}")
    return "，".join(parts)


def _product_summary(product, completed_count: int, total: int) -> str:
    recommendation = {
        "recommend": "推荐",
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
