"""
SupplyRiskAgent A2A Server (端口 5103) — MCP Tool Calling 版
"""
import json, sys
from pathlib import Path
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import SUPPLY_RISK_MCP_URL
from a2a_base import AgentCard, create_a2a_app, call_llm, parse_json_from_llm
from a2a_react import create_agent_executor, format_query_result, load_mcp_tools_from_url
from create_logger import get_logger

logger = get_logger("SupplyRiskAgent")

CARD = AgentCard(
    name="SupplyRiskAgent", version="2.1.0",
    description="负责电商选品中的供应链、备货建议和风险评估（MCP Tool Calling 版）。",
    url="http://localhost:5103",
    capabilities={"streaming": False, "memory": False},
    skills=[{"name": "analyze supply chain risk", "description": "评估供应商可靠性、建议备货量和风险等级", "examples": ["分析商品 101 的供应风险"]}],
)

SYSTEM_PROMPT = """你是电商选品供应链风险分析 Agent。调用 MCP 工具后输出 JSON:
{
  "agent": "SupplyRiskAgent", "product_id": 商品ID, "status": "success",
  "scores": {"supply_score": 0-100, "risk_score": 0-100},
  "summary": "一句中文总结供应链和风险",
  "details": {"risk_level": "low/medium/high", "lead_time_days": 交期, "moq": 起订量, "initial_stock_suggestion": 备货建议, "risk_items": ["风险项"]},
  "suggestions": ["建议"], "error": null
}
只输出 JSON。"""

_executor = None


async def get_executor():
    global _executor
    if _executor is None:
        tools = await load_mcp_tools_from_url(SUPPLY_RISK_MCP_URL)
        _executor = create_agent_executor(tools, SYSTEM_PROMPT)
        logger.info("SupplyRiskAgent MCP 工具加载完成: %d 个工具", len(tools))
    return _executor


async def handle_task(input_data: dict, task_logger) -> dict:
    product = input_data.get("product", {})
    constraints = input_data.get("constraints", {})
    product_id = product.get("product_id", 0)
    category = constraints.get("category") or product.get("category", "")

    query = f"""分析商品供应链和风险:
商品: {product.get('product_name', '')} (ID={product_id}) 类目: {category} 月销量: {product.get('monthly_sales', 100)}
先调用 query_supplier，再调用 evaluate_product_risk 和 suggest_initial_stock，输出 JSON。"""

    try:
        executor = await get_executor()
        return await format_query_result(query, executor, product_id, "SupplyRiskAgent")
    except Exception as e:
        logger.error("MCP Tool Calling SupplyRiskAgent 失败: %s", e)
        from prompts import SUPPLY_RISK_AGENT_SYSTEM_V1
        llm_output = await __import__("asyncio").to_thread(call_llm, SUPPLY_RISK_AGENT_SYSTEM_V1, json.dumps({"product": product, "constraints": constraints}, ensure_ascii=False))
        result = parse_json_from_llm(llm_output)
        result.setdefault("agent", "SupplyRiskAgent"); result.setdefault("product_id", product_id); result.setdefault("status", "success")
        return result


app = create_a2a_app(CARD, handle_task)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5103)
