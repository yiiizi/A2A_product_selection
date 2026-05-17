"""
MCP Supply Risk Server (端口 8103) — fastmcp 版
提供供应商查询、备货建议、风险评估工具。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import FastMCP
from sqlalchemy import text
from database import SessionLocal
from create_logger import get_logger

logger = get_logger("mcp_supply_risk_server")
mcp = FastMCP("Supply Risk MCP Server", version="2.0.0")


@mcp.tool()
def query_supplier(product_id: int) -> dict:
    """查询商品的供应商信息（交期、起订量、可靠性评分）。

    参数:
        product_id: 商品ID
    """
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT supplier_name, contact, lead_time_days, moq, reliability_score, location
            FROM suppliers WHERE product_id = :pid
        """), {"pid": product_id})
        rows = result.fetchall()

        suppliers = []
        for r in rows:
            suppliers.append({
                "name": r[0], "contact": r[1], "lead_time_days": r[2],
                "moq": r[3], "reliability_score": float(r[4]), "location": r[5],
            })

        avg_reliability = sum(s["reliability_score"] for s in suppliers) / len(suppliers) if suppliers else 70
        avg_lead_time = sum(s["lead_time_days"] for s in suppliers) / len(suppliers) if suppliers else 10

        return {
            "product_id": product_id, "supplier_count": len(suppliers),
            "avg_reliability": round(avg_reliability, 1),
            "avg_lead_time": round(avg_lead_time, 1),
            "suppliers": suppliers,
        }
    finally:
        session.close()


@mcp.tool()
def suggest_initial_stock(product_id: int, expected_monthly_sales: int = 100) -> dict:
    """根据预期月销量和供应商交期建议首批备货量。

    参数:
        product_id: 商品ID
        expected_monthly_sales: 预期月销量
    """
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT MIN(moq), AVG(lead_time_days) FROM suppliers WHERE product_id = :pid
        """), {"pid": product_id})
        row = result.fetchone()

        min_moq = row[0] if row and row[0] else 100
        avg_lead_time = int(row[1]) if row and row[1] else 10

        daily_sales = expected_monthly_sales / 30
        safety_stock = int(avg_lead_time * daily_sales * 1.5)
        suggested = max(min_moq, expected_monthly_sales + safety_stock)
        suggested = ((suggested + 99) // 100) * 100

        return {
            "product_id": product_id, "expected_monthly_sales": expected_monthly_sales,
            "min_moq": min_moq, "avg_lead_time_days": avg_lead_time,
            "initial_stock_suggestion": suggested,
        }
    finally:
        session.close()


@mcp.tool()
def evaluate_product_risk(product_id: int, category: str = "") -> dict:
    """评估商品的风险等级（合规/IP/安全/退货风险）。

    参数:
        product_id: 商品ID
        category: 商品类目（为空则从数据库查找）
    """
    session = SessionLocal()
    try:
        cat = category
        if not cat:
            row = session.execute(text(
                "SELECT category FROM candidate_products WHERE product_id = :pid"
            ), {"pid": product_id}).fetchone()
            cat = row[0] if row else "未知"

        result = session.execute(text("""
            SELECT rule_type, risk_level, description
            FROM risk_rules WHERE category = :cat AND is_active = 1
        """), {"cat": cat})
        rows = result.fetchall()

        risk_items = []
        high_count = medium_count = low_count = 0

        for r in rows:
            risk_items.append({"type": r[0], "level": r[1], "description": r[2]})
            if r[1] == "high":
                high_count += 1
            elif r[1] == "medium":
                medium_count += 1
            else:
                low_count += 1

        if high_count > 0:
            risk_level = "high"
        elif medium_count >= 2:
            risk_level = "medium"
        else:
            risk_level = "low"

        risk_score = max(20, 100 - high_count * 20 - medium_count * 10)

        return {
            "product_id": product_id, "category": cat,
            "risk_level": risk_level, "risk_score": risk_score,
            "high_risk_count": high_count, "medium_risk_count": medium_count,
            "low_risk_count": low_count, "risk_items": risk_items,
        }
    finally:
        session.close()


if __name__ == "__main__":
    logger.info("Starting MCP Supply Risk Server (fastmcp) on port 8103")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8103, path="/mcp")
