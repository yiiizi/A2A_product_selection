"""
ProfitAgent A2A Server (端口 5102) — MCP Tool Calling 版
"""
import json, sys
from pathlib import Path
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PROFIT_MCP_URL
from a2a_base import AgentCard, create_a2a_app, call_llm, parse_json_from_llm
from a2a_react import create_agent_executor, format_query_result, load_mcp_tools_from_url
from create_logger import get_logger

logger = get_logger("ProfitAgent")

CARD = AgentCard(
    name="ProfitAgent", version="2.1.0",
    description="负责电商选品中的利润测算、建议售价和盈亏平衡分析（MCP Tool Calling 版）。",
    url="http://localhost:5102",
    capabilities={"streaming": False, "memory": False},
    skills=[{"name": "analyze profitability", "description": "测算利润空间、建议售价和盈亏平衡销量", "examples": ["分析商品 101 的利润空间"]}],
)

SYSTEM_PROMPT = """你是电商选品利润测算 Agent。调用 MCP 工具获取成本、售价和盈亏平衡数据后输出 JSON:
{
  "agent": "ProfitAgent", "product_id": 商品ID, "status": "success",
  "scores": {"profit_score": 0-100},
  "summary": "一句中文总结利润空间",
  "details": {"gross_margin": 毛利率, "suggested_price": 建议售价, "break_even_units": 盈亏平衡销量},
  "suggestions": ["建议"], "error": null
}
只输出 JSON。"""

_executor = None


async def get_executor():
    global _executor
    if _executor is None:
        tools = await load_mcp_tools_from_url(PROFIT_MCP_URL)
        _executor = create_agent_executor(tools, SYSTEM_PROMPT)
        logger.info("ProfitAgent MCP 工具加载完成: %d 个工具", len(tools))
    return _executor


async def handle_task(input_data: dict, task_logger) -> dict:
    product = input_data.get("product", {})
    constraints = input_data.get("constraints", {})
    product_id = product.get("product_id", 0)

    query = f"""分析商品利润率:
商品: {product.get('product_name', '')} (ID={product_id})
售价: {product.get('target_price', 0)} 元
偏好: {constraints.get('preferences', [])}

先调用 calculate_profit，再调用 suggest_price 和 calculate_break_even，输出 JSON。"""

    try:
        executor = await get_executor()
        return await format_query_result(query, executor, product_id, "ProfitAgent")
    except Exception as e:
        logger.error("MCP Tool Calling ProfitAgent 失败: %s", e)
        from prompts import PROFIT_AGENT_SYSTEM_V1
        llm_output = await __import__("asyncio").to_thread(call_llm, PROFIT_AGENT_SYSTEM_V1, json.dumps({"product": product, "constraints": constraints}, ensure_ascii=False))
        result = parse_json_from_llm(llm_output)
        result.setdefault("agent", "ProfitAgent"); result.setdefault("product_id", product_id); result.setdefault("status", "success")
        return result


app = create_a2a_app(CARD, handle_task)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5102)
