"""
MCP Profit Server (端口 8102) — fastmcp 版
提供利润测算、建议售价、盈亏平衡点计算工具。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import FastMCP
from sqlalchemy import text
from database import SessionLocal
from create_logger import get_logger

logger = get_logger("mcp_profit_server")
mcp = FastMCP("Profit MCP Server", version="2.0.0")


def _get_product_cost(session, product_id: int) -> dict | None:
    result = session.execute(text("""
        SELECT c.product_id, c.product_name, c.price, c.category,
               pc.purchase_cost, pc.platform_fee_rate, pc.shipping_cost,
               pc.ad_cost_rate, pc.other_cost
        FROM candidate_products c
        LEFT JOIN product_costs pc ON c.product_id = pc.product_id
        WHERE c.product_id = :pid
    """), {"pid": product_id})
    row = result.fetchone()
    if not row:
        return None
    return {
        "product_id": row[0], "product_name": row[1], "current_price": float(row[2]),
        "category": row[3], "purchase_cost": float(row[4]) if row[4] else 0,
        "platform_fee_rate": float(row[5]) if row[5] else 5.0,
        "shipping_cost": float(row[6]) if row[6] else 0,
        "ad_cost_rate": float(row[7]) if row[7] else 3.0,
        "other_cost": float(row[8]) if row[8] else 0,
    }


@mcp.tool()
def calculate_profit(product_id: int, target_price: float = 0) -> dict:
    """计算商品的利润（毛利、毛利率、净利润和利润评分）。

    参数:
        product_id: 商品ID
        target_price: 目标售价（传0则使用当前售价）
    """
    session = SessionLocal()
    try:
        product = _get_product_cost(session, product_id)
        if not product:
            return {"error": f"商品 {product_id} 不存在"}

        price = target_price if target_price > 0 else product["current_price"]
        platform_fee = price * product["platform_fee_rate"] / 100
        ad_cost = price * product["ad_cost_rate"] / 100
        total_cost = product["purchase_cost"] + platform_fee + product["shipping_cost"] + ad_cost + product["other_cost"]
        gross_profit = price - total_cost
        gross_margin = (gross_profit / price * 100) if price > 0 else 0

        if gross_margin >= 40:
            profit_score = 90
        elif gross_margin >= 30:
            profit_score = 80
        elif gross_margin >= 20:
            profit_score = 70
        elif gross_margin >= 10:
            profit_score = 60
        else:
            profit_score = 40

        return {
            "product_id": product_id, "product_name": product["product_name"],
            "target_price": price, "purchase_cost": product["purchase_cost"],
            "platform_fee": round(platform_fee, 2), "shipping_cost": product["shipping_cost"],
            "ad_cost": round(ad_cost, 2), "other_cost": product["other_cost"],
            "total_cost": round(total_cost, 2), "gross_profit": round(gross_profit, 2),
            "gross_margin": round(gross_margin, 1), "profit_score": profit_score,
        }
    finally:
        session.close()


@mcp.tool()
def suggest_price(product_id: int, min_margin: float = 20.0) -> dict:
    """根据商品成本和最低毛利率反推建议售价。

    参数:
        product_id: 商品ID
        min_margin: 最低毛利率%（默认20）
    """
    session = SessionLocal()
    try:
        product = _get_product_cost(session, product_id)
        if not product:
            return {"error": f"商品 {product_id} 不存在"}

        denominator = 1 - product["platform_fee_rate"] / 100 - product["ad_cost_rate"] / 100 - min_margin / 100
        if denominator <= 0:
            return {"error": "费率设置不合理，无法满足最低毛利率"}

        base_cost = product["purchase_cost"] + product["shipping_cost"] + product["other_cost"]
        suggested_price = base_cost / denominator
        # 取整到 9 的倍数（心理定价）
        rounded = int(suggested_price / 10) * 10 + 9
        if rounded < suggested_price:
            rounded += 10

        return {
            "product_id": product_id, "min_margin": min_margin,
            "suggested_price": rounded,
            "suggested_price_exact": round(suggested_price, 2),
            "current_price": product["current_price"],
        }
    finally:
        session.close()


@mcp.tool()
def calculate_break_even(product_id: int, fixed_cost: float = 0) -> dict:
    """计算盈亏平衡点销量。

    参数:
        product_id: 商品ID
        fixed_cost: 固定成本（营销/包装等一次性费用）
    """
    session = SessionLocal()
    try:
        product = _get_product_cost(session, product_id)
        if not product:
            return {"error": f"商品 {product_id} 不存在"}

        price = product["current_price"]
        variable_cost = (product["purchase_cost"] + price * product["platform_fee_rate"] / 100
                         + price * product["ad_cost_rate"] / 100 + product["shipping_cost"])
        unit_margin = price - variable_cost

        if unit_margin <= 0:
            return {"product_id": product_id, "error": "单位毛利为负，无法计算盈亏平衡", "break_even_units": -1}

        be_units = max(1, int(fixed_cost / unit_margin + 1))
        return {
            "product_id": product_id, "fixed_cost": fixed_cost,
            "unit_margin": round(unit_margin, 2), "break_even_units": be_units,
        }
    finally:
        session.close()


if __name__ == "__main__":
    logger.info("Starting MCP Profit Server (fastmcp) on port 8102")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8102, path="/mcp")
