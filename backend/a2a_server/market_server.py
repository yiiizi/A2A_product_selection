"""
MarketAgent A2A Server (端口 5101) — MCP Tool Calling 版
通过 MCP streamable-http 协议自动发现并加载 Market MCP Server 的工具。
"""
import json
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import MARKET_MCP_URL
from a2a_base import AgentCard, create_a2a_app, call_llm, parse_json_from_llm
from a2a_react import (
    create_agent_executor, format_query_result,
    load_mcp_tools_for_agent, load_mcp_tools_from_url,
)
from create_logger import get_logger

logger = get_logger("MarketAgent")

CARD = AgentCard(
    name="MarketAgent",
    description="负责电商选品中的市场趋势、竞品和价格带分析（MCP Tool Calling 版）。",
    url="http://localhost:5101",
    version="2.1.0",
    capabilities={"streaming": False, "memory": False},
    skills=[
        {
            "name": "analyze market and competitors",
            "description": "分析商品类目的市场趋势、竞品强度、价格带和差异化机会。",
            "examples": ["分析家居小电器 100-300 元价格带的市场机会"],
        }
    ],
)

SYSTEM_PROMPT = """你是电商选品市场趋势分析 Agent。你可以调用 MCP 工具获取市场趋势、竞品数据和价格带分析数据。

工作流程:
1. 先调用 query_market_trends 获取趋势
2. 调用 query_competitor_products 获取竞品数据
3. 可选调用 analyze_price_band 确认价格带
4. 综合数据，输出 JSON 格式的分析结果

输出格式:
{
  "agent": "MarketAgent", "product_id": 商品ID, "status": "success",
  "scores": {"trend_score": 0-100, "competition_score": 0-100},
  "summary": "用一句中文总结市场机会和竞争压力",
  "details": {"price_band": "价格带判断", "differentiation_opportunity": "差异化机会"},
  "suggestions": ["可执行建议1", "可执行建议2"],
  "error": null
}
只输出 JSON，不要输出 Markdown。"""

_executor = None  # 延迟初始化


async def get_executor():
    """延迟加载 MCP 工具并创建 Agent Executor（带缓存）。

    v3.0: 使用 load_mcp_tools_for_agent 从多个 MCP Server 加载工具。
    降级: 如果多 MCP 加载失败，回退到单 MARKET_MCP_URL。
    """
    global _executor
    if _executor is None:
        tools = await load_mcp_tools_for_agent("MarketAgent")
        if not tools:
            # 降级: 直接用单 MCP URL
            tools = await load_mcp_tools_from_url(MARKET_MCP_URL)
        _executor = create_agent_executor(tools, SYSTEM_PROMPT)
        logger.info("MarketAgent MCP 工具加载完成: %d 个工具", len(tools))
    return _executor


async def handle_task(input_data: dict, task_logger) -> dict:
    product = input_data.get("product", {})
    constraints = input_data.get("constraints", {})
    product_id = product.get("product_id", 0)

    category = constraints.get("category") or product.get("category", "")
    price_min = constraints.get("price_min") or 0
    price_max = constraints.get("price_max") or 99999
    season = constraints.get("season") or ""

    query = f"""请分析以下商品的市场情况。

商品: {product.get('product_name', '')} (ID={product_id})
类目: {category}
价格区间: {price_min}-{price_max} 元
季节: {season or '不限'}
描述: {product.get('description', '')[:200]}

请按顺序调用工具获取数据，然后输出 JSON 分析结果。"""

    try:
        executor = await get_executor()
        return await format_query_result(query, executor, product_id, "MarketAgent")
    except Exception as e:
        logger.error("MCP Tool Calling MarketAgent 失败: %s", e)
        from prompts import MARKET_AGENT_SYSTEM_V1
        user_content = json.dumps({"product": product, "constraints": constraints, "message": "请分析该商品的市场情况，输出 JSON。"}, ensure_ascii=False)
        llm_output = await __import__("asyncio").to_thread(call_llm, MARKET_AGENT_SYSTEM_V1, user_content)
        result = parse_json_from_llm(llm_output)
        result.setdefault("agent", "MarketAgent")
        result.setdefault("product_id", product_id)
        result.setdefault("status", "success")
        return result


app = create_a2a_app(CARD, handle_task)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5101)
