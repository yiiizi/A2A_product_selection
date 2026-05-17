"""
ProductSelectionOrchestrator

负责解析选品需求、调度 4 个 A2A 智能体、汇总评分并生成最终选品报告。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from datetime import datetime
from typing import Any

import httpx
from openai import OpenAI
from sqlalchemy import text

from config import (
    MARKET_A2A_URL, PROFIT_A2A_URL, SUPPLY_RISK_A2A_URL, REVIEW_A2A_URL,
    A2A_TIMEOUT_SECONDS, MOCK_A2A, MOCK_LLM,
    API_KEY, BASE_URL, LLM_MODEL, LLM_TEMPERATURE,
)
from create_logger import get_logger
from database import SessionLocal
from prompts import PARSE_SELECTION_REQUEST_V1, GENERATE_REPORT_V1
from schemas import AgentResult, Constraints, ProductAnalysisResult, SelectionReport, SelectionRequest
from scoring import DEFAULT_SCORES, calculate_final_score, get_recommendation

logger = get_logger("selection_service")

A2A_AGENTS = {
    "MarketAgent": MARKET_A2A_URL,
    "ProfitAgent": PROFIT_A2A_URL,
    "SupplyRiskAgent": SUPPLY_RISK_A2A_URL,
    "ReviewInsightAgent": REVIEW_A2A_URL,
}

AGENT_LABELS = {
    "MarketAgent": "市场趋势分析",
    "ProfitAgent": "利润测算",
    "SupplyRiskAgent": "供应链与风险",
    "ReviewInsightAgent": "评论洞察",
}


def parse_selection_request(user_query: str) -> Constraints:
    """用 LLM 解析选品需求；演示模式下使用轻量规则兜底。"""
    if MOCK_LLM:
        prices = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", user_query)]
        price_min = min(prices) if len(prices) >= 2 else None
        price_max = max(prices) if len(prices) >= 2 else None
        season = "夏季" if "夏" in user_query else None
        preferences = []
        for keyword in ["高利润", "利润率高", "竞争不要太激烈", "低竞争", "上新"]:
            if keyword in user_query:
                preferences.append(keyword)
        return Constraints(
            category=None,
            price_min=price_min,
            price_max=price_max,
            season=season,
            preferences=preferences,
        )

    from a2a_server.a2a_base import call_llm, parse_json_from_llm

    prompt = PARSE_SELECTION_REQUEST_V1.format(user_query=user_query)
    output = call_llm("你是电商选品需求解析助手。", prompt)
    data = parse_json_from_llm(output)

    return Constraints(
        category=data.get("category"),
        price_min=data.get("price_min"),
        price_max=data.get("price_max"),
        season=data.get("season"),
        preferences=data.get("preferences", []),
    )


def query_candidate_products(constraints: Constraints, top_k: int = 10) -> list[dict]:
    session = SessionLocal()
    try:
        def fetch(ignore_category: bool = False):
            conditions = []
            params: dict[str, Any] = {"lim": top_k}

            if constraints.category and not ignore_category:
                conditions.append("category = :cat")
                params["cat"] = constraints.category
            if constraints.price_min is not None:
                conditions.append("price >= :pmin")
                params["pmin"] = constraints.price_min
            if constraints.price_max is not None:
                conditions.append("price <= :pmax")
                params["pmax"] = constraints.price_max

            where = " AND ".join(conditions) if conditions else "1=1"
            return session.execute(text(f"""
                SELECT product_id, product_name, category, price, monthly_sales, rating, description
                FROM candidate_products
                WHERE {where}
                ORDER BY monthly_sales DESC, rating DESC
                LIMIT :lim
            """), params).fetchall()

        rows = fetch(ignore_category=False)

        return [
            {
                "product_id": r[0],
                "product_name": r[1],
                "category": r[2],
                "target_price": float(r[3]),
                "monthly_sales": r[4],
                "rating": float(r[5]),
                "description": r[6] or "",
            }
            for r in rows
        ]
    finally:
        session.close()


async def call_a2a_agent(agent_name: str, agent_url: str, input_data: dict) -> AgentResult:
    product_id = input_data.get("product", {}).get("product_id", 0)

    if MOCK_A2A:
        return _mock_agent_result(agent_name, product_id)

    task_id = f"task-{agent_name}-{product_id}-{int(time.time() * 1000)}"
    payload = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "id": task_id,
            "message": {
                "role": "user",
                "parts": [{"text": json.dumps(input_data, ensure_ascii=False)}],
            },
        },
        "id": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=A2A_TIMEOUT_SECONDS) as client:
            resp = await client.post(f"{agent_url}/tasks/send", json=payload)
            resp.raise_for_status()
            data = resp.json()

        result_data = data.get("result", {})
        status = result_data.get("status", "failed")

        if status == "completed":
            artifacts = result_data.get("artifacts", [])
            if artifacts:
                parts = artifacts[0].get("parts", [])
                if parts:
                    agent_output = json.loads(parts[0].get("text", "{}"))
                    return AgentResult(
                        agent=agent_name,
                        product_id=product_id,
                        status="success",
                        scores=agent_output.get("scores", {}),
                        summary=agent_output.get("summary", ""),
                        details=agent_output.get("details", {}),
                        suggestions=agent_output.get("suggestions", []),
                    )

        return AgentResult(
            agent=agent_name,
            product_id=product_id,
            status="failed",
            error=result_data.get("error", "智能体未返回有效结果"),
        )

    except httpx.TimeoutException as e:
        error_message = f"{agent_name} 调用超时，当前 A2A_TIMEOUT_SECONDS={A2A_TIMEOUT_SECONDS} 秒；该智能体可能仍在后台执行，请稍后重试或继续调高超时时间。"
        logger.error("调用 %s 超时: %r", agent_name, e)
        return AgentResult(
            agent=agent_name,
            product_id=product_id,
            status="failed",
            error=error_message,
        )
    except httpx.HTTPError as e:
        error_message = str(e) or repr(e) or e.__class__.__name__
        logger.error("调用 %s HTTP 失败: %s", agent_name, error_message)
        return AgentResult(
            agent=agent_name,
            product_id=product_id,
            status="failed",
            error=error_message,
        )
    except Exception as e:
        error_message = str(e) or repr(e) or e.__class__.__name__
        logger.error("调用 %s 失败: %s", agent_name, error_message)
        return AgentResult(
            agent=agent_name,
            product_id=product_id,
            status="failed",
            error=error_message,
        )


def _mock_agent_result(agent_name: str, product_id: int) -> AgentResult:
    defaults = DEFAULT_SCORES.get(agent_name, {})
    label = AGENT_LABELS.get(agent_name, agent_name)
    return AgentResult(
        agent=agent_name,
        product_id=product_id,
        status="success",
        scores=defaults,
        summary=f"{label}已返回演示评分，建议接入真实 MCP 数据后复核。",
        details={},
        suggestions=["用于演示时可先小批量验证，正式选品前需要补齐真实业务数据。"],
    )


def select_agents(user_intent=None, slots: dict | None = None) -> dict:
    """根据用户意图和槽位动态选择 Agent 组合，减少不必要的 LLM 调用。

    默认返回 4 个 Agent，传入 user_intent 时按需精简。
    """
    agents = dict(A2A_AGENTS)  # 默认全部

    if user_intent is not None:
        agents = {}
        goal = getattr(user_intent, "goal", "profit_first")
        experience = getattr(user_intent, "experience_level", "intermediate")
        preferences = (slots or {}).get("preferences", [])

        # 市场分析：默认需要
        agents["MarketAgent"] = A2A_AGENTS["MarketAgent"]

        # 利润分析：利润优先或老手时需要
        if goal in ("profit_first",) or experience == "veteran":
            agents["ProfitAgent"] = A2A_AGENTS["ProfitAgent"]

        # 供应链风险：规避风险或新手时需要
        if goal == "risk_averse" or experience == "newbie" or "低风险" in preferences:
            agents["SupplyRiskAgent"] = A2A_AGENTS["SupplyRiskAgent"]

        # 评论洞察：追趋势或新手时需要
        if goal == "trend_chasing" or experience == "newbie":
            agents["ReviewInsightAgent"] = A2A_AGENTS["ReviewInsightAgent"]

        # 兜底：至少 2 个核心 Agent
        if len(agents) < 2:
            agents["ProfitAgent"] = A2A_AGENTS["ProfitAgent"]
            agents["ReviewInsightAgent"] = A2A_AGENTS["ReviewInsightAgent"]

    return agents


async def analyze_single_product(
    product: dict,
    constraints: Constraints,
    user_query: str,
    agents: dict | None = None,
) -> ProductAnalysisResult:
    product_id = product["product_id"]
    agents = agents or A2A_AGENTS
    agent_count = len(agents)
    logger.info("开始分析商品: %s (ID=%d, agents=%d)", product["product_name"], product_id, agent_count)

    input_data = {
        "request_id": f"req-{uuid.uuid4().hex[:8]}",
        "product": product,
        "constraints": {
            "category": constraints.category,
            "price_min": constraints.price_min,
            "price_max": constraints.price_max,
            "season": constraints.season,
            "preferences": constraints.preferences,
        },
        "context": {"user_query": user_query},
    }

    semaphore = asyncio.Semaphore(agent_count)

    async def _call_with_semaphore(name: str, url: str):
        async with semaphore:
            return await call_a2a_agent(name, url, input_data)

    tasks = [_call_with_semaphore(name, url) for name, url in agents.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    agent_results: dict[str, AgentResult] = {}
    for i, (name, _) in enumerate(agents.items()):
        result = results[i]
        if isinstance(result, Exception):
            agent_results[name] = AgentResult(
                agent=name,
                product_id=product_id,
                status="failed",
                error=str(result),
            )
        else:
            agent_results[name] = result

    final_score, score_breakdown = calculate_final_score(agent_results)
    recommendation = get_recommendation(final_score)

    highlights = []
    risks = []
    for name, result in agent_results.items():
        label = AGENT_LABELS.get(name, name)
        if result.status == "success":
            if result.summary:
                highlights.append(f"{label}：{result.summary}")
        else:
            risks.append(f"{label}分析失败：{result.error or '未知错误'}")

    return ProductAnalysisResult(
        product_id=product_id,
        product_name=product.get("product_name", ""),
        category=product.get("category", ""),
        final_score=final_score,
        agent_results=agent_results,
        score_breakdown=score_breakdown,
        recommendation=recommendation,
        highlights=highlights,
        risks=risks,
    )


async def generate_report(user_query: str, products: list[ProductAnalysisResult]) -> str:
    """最终选品报告独立调用真实大模型；失败时返回可读的本地兜底报告。"""
    products_json = json.dumps(
        [_product_for_report(p) for p in products],
        ensure_ascii=False,
        indent=2,
        default=str,
    )

    prompt = GENERATE_REPORT_V1.format(
        current_date=datetime.now().strftime("%Y-%m-%d"),
        user_query=user_query,
        products_json=products_json,
    )

    if not API_KEY:
        logger.warning("未配置 API_KEY，最终报告使用本地兜底报告。")
        return _mock_report(user_query, products)

    try:
        content = await asyncio.to_thread(_call_report_llm, prompt)
        return content or _mock_report(user_query, products)
    except Exception as e:
        logger.error("最终报告大模型调用失败，使用本地兜底报告: %s", e)
        return _mock_report(user_query, products)


def _call_report_llm(prompt: str) -> str:
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    completion = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": "你是电商选品报告撰写专家，输出务实、清晰、可执行的中文报告。"},
            {"role": "user", "content": prompt},
        ],
        temperature=LLM_TEMPERATURE,
    )
    return completion.choices[0].message.content or ""


def _product_for_report(product: ProductAnalysisResult) -> dict:
    return {
        "product_id": product.product_id,
        "product_name": product.product_name,
        "category": product.category,
        "final_score": product.final_score,
        "recommendation": product.recommendation,
        "score_breakdown": product.score_breakdown,
        "highlights": product.highlights,
        "risks": product.risks,
        "agent_results": {
            name: {
                "agent_name": AGENT_LABELS.get(name, name),
                "status": result.status,
                "scores": result.scores,
                "summary": result.summary,
                "details": _compact_value(result.details),
                "suggestions": result.suggestions,
                "error": result.error,
            }
            for name, result in product.agent_results.items()
        },
    }


def _compact_value(value: Any, depth: int = 0) -> Any:
    if depth >= 4:
        return str(value)[:300]
    if isinstance(value, dict):
        return {k: _compact_value(v, depth + 1) for k, v in list(value.items())[:12]}
    if isinstance(value, list):
        return [_compact_value(v, depth + 1) for v in value[:6]]
    if isinstance(value, str):
        return value[:800]
    return value


def _recommendation_text(rec: str) -> str:
    if rec == "recommend":
        return "建议选品"
    if rec == "neutral":
        return "谨慎观察"
    return "暂不建议"


def _mock_report(user_query: str, products: list[ProductAnalysisResult]) -> str:
    lines = [
        "# 选品报告",
        "",
        f"**选品需求**：{user_query}",
        "",
        "## 整体结论",
    ]
    if products:
        best = products[0]
        lines.append(
            f"优先关注「{best.product_name}」，当前综合评分 {best.final_score}，"
            f"系统建议为「{_recommendation_text(best.recommendation)}」。"
        )
    else:
        lines.append("当前没有筛选出符合条件的候选商品，需要放宽价格、类目或上新条件。")

    for product in products:
        lines.extend([
            "",
            f"## {product.product_name}",
            f"- 推荐等级：{_recommendation_text(product.recommendation)}",
            f"- 综合评分：{product.final_score}",
            f"- 评分拆解：{product.score_breakdown}",
        ])
        if product.highlights:
            lines.append("- 关键依据：" + "；".join(product.highlights[:4]))
        if product.risks:
            lines.append("- 风险提醒：" + "；".join(product.risks[:3]))
        lines.append("- 执行动作：建议先做小批量试卖，复核供应商交期、成本和评价痛点，再决定是否扩大备货。")

    return "\n".join(lines)


def save_selection_report(request_id: str, user_query: str, constraints: Constraints,
                          products: list[ProductAnalysisResult], final_report: str):
    session = SessionLocal()
    try:
        products_data = [p.model_dump() for p in products]
        session.execute(text("""
            INSERT INTO selection_reports (request_id, user_query, constraints_json, products_json, final_report)
            VALUES (:rid, :query, :cons, :prods, :report)
            ON DUPLICATE KEY UPDATE final_report=VALUES(final_report)
        """), {
            "rid": request_id,
            "query": user_query,
            "cons": json.dumps(constraints.model_dump(), ensure_ascii=False),
            "prods": json.dumps(products_data, ensure_ascii=False, default=str),
            "report": final_report,
        })
        session.commit()
    except Exception as e:
        logger.error("保存选品报告失败: %s", e)
        session.rollback()
    finally:
        session.close()


def save_agent_logs(request_id: str, products: list[ProductAnalysisResult]):
    session = SessionLocal()
    try:
        for product in products:
            for agent_name, result in product.agent_results.items():
                session.execute(text("""
                    INSERT INTO agent_call_logs (request_id, agent_name, product_id, status, input_json, output_json, error_message)
                    VALUES (:rid, :agent, :pid, :status, :input, :output, :err)
                """), {
                    "rid": request_id,
                    "agent": agent_name,
                    "pid": product.product_id,
                    "status": result.status,
                    "input": None,
                    "output": json.dumps(result.model_dump(), ensure_ascii=False, default=str),
                    "err": result.error,
                })
        session.commit()
    except Exception as e:
        logger.error("保存 Agent 调用日志失败: %s", e)
        session.rollback()
    finally:
        session.close()


async def run_selection(request: SelectionRequest) -> SelectionReport:
    request_id = f"req-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
    start_time = time.time()

    logger.info("开始选品分析 [%s] %s", request_id, request.query)

    constraints = parse_selection_request(request.query)
    logger.info("解析后的约束: %s", constraints.model_dump())

    candidate_count = min(request.top_k * 3, 20)
    candidates = query_candidate_products(constraints, top_k=candidate_count)
    logger.info("候选商品数量: %d", len(candidates))

    if not candidates:
        return SelectionReport(
            request_id=request_id,
            query=request.query,
            constraints=constraints,
            products=[],
            final_report="没有找到符合条件的候选商品，请尝试放宽价格区间、类目或偏好条件。",
        )

    # 只对最终需要返回的候选做完整 A2A 分析。候选池可以更大，但不要把所有候选都送进 4 个 Agent。
    # top_k=5 时从原来的 10 个商品 * 4 Agent，降为 5 个商品 * 4 Agent。
    products_to_analyze = candidates[: max(3, request.top_k // 2)]
    analysis_tasks = [
        analyze_single_product(product, constraints, request.query, agents=A2A_AGENTS)
        for product in products_to_analyze
    ]
    results = await asyncio.gather(*analysis_tasks, return_exceptions=True)

    products: list[ProductAnalysisResult] = []
    for result in results:
        if isinstance(result, ProductAnalysisResult):
            products.append(result)
        elif isinstance(result, Exception):
            logger.error("商品分析失败: %s", result)

    products.sort(key=lambda p: p.final_score, reverse=True)
    products = products[:request.top_k]

    for i, product in enumerate(products):
        product.rank = i + 1

    final_report = await generate_report(request.query, products)

    save_selection_report(request_id, request.query, constraints, products, final_report)
    save_agent_logs(request_id, products)

    elapsed = time.time() - start_time
    logger.info("选品分析完成 [%s] 耗时 %.1f 秒，返回 %d 个商品", request_id, elapsed, len(products))

    return SelectionReport(
        request_id=request_id,
        query=request.query,
        constraints=constraints,
        products=products,
        final_report=final_report,
        created_at=datetime.now(),
    )
