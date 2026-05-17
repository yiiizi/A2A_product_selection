"""
选品 API 路由
"""

import json
from fastapi import APIRouter
from sqlalchemy import text

from schemas import SelectionRequest, SelectionResponse, ErrorResponse
from selection_service import run_selection
from database import SessionLocal
from create_logger import get_logger

logger = get_logger("api_selection")
router = APIRouter()


@router.post("/analyze", response_model=SelectionResponse)
async def analyze(request: SelectionRequest):
    """执行选品分析。"""
    try:
        report = await run_selection(request)
        return SelectionResponse(
            status="success",
            request_id=report.request_id,
            data=report,
        )
    except Exception as e:
        logger.error("选品分析失败: %s", e)
        return SelectionResponse(
            status="error",
            request_id="",
            data=None,
        )


@router.get("/reports")
async def list_reports(page: int = 1, size: int = 10):
    """获取历史选品报告列表。"""
    session = SessionLocal()
    try:
        offset = (page - 1) * size
        result = session.execute(text("""
            SELECT request_id, user_query, created_at
            FROM selection_reports ORDER BY created_at DESC
            LIMIT :lim OFFSET :offset
        """), {"lim": size, "offset": offset})
        rows = result.fetchall()

        count_result = session.execute(text("SELECT COUNT(*) FROM selection_reports"))
        total = count_result.scalar()

        return {
            "status": "success",
            "total": total,
            "page": page,
            "size": size,
            "data": [
                {"request_id": r[0], "query": r[1], "created_at": str(r[2])}
                for r in rows
            ],
        }
    finally:
        session.close()


@router.get("/reports/{report_id}")
async def get_report(report_id: str):
    """获取单个选品报告详情。"""
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT request_id, user_query, constraints_json, products_json, final_report, created_at
            FROM selection_reports WHERE request_id = :rid
        """), {"rid": report_id})
        row = result.fetchone()

        if not row:
            return {"status": "error", "message": "报告不存在"}

        return {
            "status": "success",
            "data": {
                "request_id": row[0],
                "query": row[1],
                "constraints": json.loads(row[2]) if row[2] else {},
                "products": json.loads(row[3]) if row[3] else [],
                "final_report": row[4],
                "created_at": str(row[5]),
            },
        }
    finally:
        session.close()


@router.get("/agents")
async def list_agents():
    """获取 Agent 列表。"""
    return {
        "status": "success",
        "agents": [
            {"name": "MarketAgent", "url": "http://localhost:5101", "description": "市场趋势、竞品分析"},
            {"name": "ProfitAgent", "url": "http://localhost:5102", "description": "利润测算、建议售价"},
            {"name": "SupplyRiskAgent", "url": "http://localhost:5103", "description": "供应链、风险评估"},
            {"name": "ReviewInsightAgent", "url": "http://localhost:5104", "description": "评论洞察、RAG 检索"},
        ],
    }


@router.get("/agent/logs")
async def get_agent_logs(request_id: str):
    """获取指定请求的 Agent 调用日志。"""
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT request_id, agent_name, product_id, status, duration_ms, error_message, created_at
            FROM agent_call_logs WHERE request_id = :rid ORDER BY created_at
        """), {"rid": request_id})
        rows = result.fetchall()

        return {
            "status": "success",
            "data": [
                {
                    "request_id": r[0],
                    "agent_name": r[1],
                    "product_id": r[2],
                    "status": r[3],
                    "duration_ms": r[4],
                    "error_message": r[5],
                    "created_at": str(r[6]),
                }
                for r in rows
            ],
        }
    finally:
        session.close()
