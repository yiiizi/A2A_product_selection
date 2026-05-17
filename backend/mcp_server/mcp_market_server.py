"""
MCP Market Server (端口 8101) — fastmcp 版
提供市场趋势、竞品分析、价格带分析工具。使用标准 MCP 协议，支持 LangChain Tool Calling。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import FastMCP
from sqlalchemy import text
from database import SessionLocal
from create_logger import get_logger

logger = get_logger("mcp_market_server")
mcp = FastMCP("Market MCP Server", version="2.0.0")


@mcp.tool()
def query_market_trends(category: str, season: str = "", keyword: str = "") -> dict:
    """查询指定类目的市场趋势数据，包括搜索量、增长率和趋势评分。

    参数:
        category: 商品类目（如"家居小电器"）
        season: 季节或场景（可选，如"夏季"）
        keyword: 关键词（可选）
    """
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT category, season, keyword, trend_score, search_volume, growth_rate
            FROM market_trends
            WHERE category = :cat
            ORDER BY
                CASE WHEN season = :season THEN 0 ELSE 1 END,
                created_at DESC
            LIMIT 5
        """), {"cat": category, "season": season})
        rows = result.fetchall()

        trends = []
        for r in rows:
            trends.append({
                "category": r[0], "season": r[1], "keyword": r[2],
                "trend_score": float(r[3]), "search_volume": r[4], "growth_rate": float(r[5]),
            })

        avg_score = sum(t["trend_score"] for t in trends) / len(trends) if trends else 60
        return {
            "category": category, "season": season,
            "avg_trend_score": round(avg_score, 1),
            "trends": trends,
        }
    finally:
        session.close()


@mcp.tool()
def query_competitor_products(category: str, price_min: float = 0, price_max: float = 99999, limit: int = 10) -> dict:
    """查询指定类目和价格区间的竞品信息，返回价格、销量和评分。

    参数:
        category: 商品类目
        price_min: 最低价格（默认0）
        price_max: 最高价格（默认99999）
        limit: 返回数量（默认10）
    """
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT cp.competitor_name, cp.competitor_price, cp.competitor_sales,
                   cp.competitor_rating, cp.platform, c.category
            FROM competitor_products cp
            JOIN candidate_products c ON cp.product_id = c.product_id
            WHERE c.category = :cat
              AND cp.competitor_price BETWEEN :pmin AND :pmax
            ORDER BY cp.competitor_sales DESC
            LIMIT :lim
        """), {"cat": category, "pmin": price_min, "pmax": price_max, "lim": limit})
        rows = result.fetchall()

        competitors = []
        for r in rows:
            competitors.append({
                "name": r[0], "price": float(r[1]), "sales": r[2],
                "rating": float(r[3]), "platform": r[4],
            })

        avg_sales = sum(c["sales"] for c in competitors) / len(competitors) if competitors else 0
        avg_rating = sum(c["rating"] for c in competitors) / len(competitors) if competitors else 0
        competition_score = min(100, int(avg_sales / 10 + avg_rating * 5 + len(competitors) * 3))

        return {
            "category": category, "competitor_count": len(competitors),
            "competition_score": competition_score,
            "avg_price": round(sum(c["price"] for c in competitors) / len(competitors), 2) if competitors else 0,
            "competitors": competitors,
        }
    finally:
        session.close()


@mcp.tool()
def analyze_price_band(category: str) -> dict:
    """分析指定类目的价格带分布，返回各区间的销量和评分统计，给出建议价格带。

    参数:
        category: 商品类目
    """
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT MIN(price) as min_price, MAX(price) as max_price,
                   AVG(price) as avg_price, COUNT(*) as cnt
            FROM candidate_products WHERE category = :cat
        """), {"cat": category})
        row = result.fetchone()

        if not row or row[3] == 0:
            return {"category": category, "price_bands": [], "suggested_band": "unknown"}

        result2 = session.execute(text("""
            SELECT
                CASE
                    WHEN price < 100 THEN '0-100'
                    WHEN price < 200 THEN '100-200'
                    WHEN price < 300 THEN '200-300'
                    ELSE '300+'
                END as band,
                COUNT(*) as cnt, AVG(monthly_sales) as avg_sales, AVG(rating) as avg_rating
            FROM candidate_products WHERE category = :cat
            GROUP BY band ORDER BY band
        """), {"cat": category})
        bands = result2.fetchall()

        price_bands = []
        for b in bands:
            price_bands.append({
                "range": b[0], "count": b[1],
                "avg_sales": round(float(b[2]), 0), "avg_rating": round(float(b[3]), 1),
            })

        best = max(price_bands, key=lambda x: x["avg_sales"]) if price_bands else None
        return {
            "category": category, "min_price": float(row[0]), "max_price": float(row[1]),
            "avg_price": round(float(row[2]), 2),
            "price_bands": price_bands,
            "suggested_band": best["range"] if best else "unknown",
        }
    finally:
        session.close()


if __name__ == "__main__":
    logger.info("Starting MCP Market Server (fastmcp) on port 8101")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8101, path="/mcp")
