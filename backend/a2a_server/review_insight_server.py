"""
ReviewInsightAgent A2A Server (端口 5104) — MCP Tool Calling 版
"""
import json, sys
from pathlib import Path
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import REVIEW_MCP_URL
from a2a_base import AgentCard, create_a2a_app, call_llm, parse_json_from_llm
from a2a_react import create_agent_executor, format_query_result, load_mcp_tools_from_url
from create_logger import get_logger

logger = get_logger("ReviewInsightAgent")

CARD = AgentCard(
    name="ReviewInsightAgent", version="2.1.0",
    description="负责电商选品中的评论洞察、用户口碑和卖点机会分析（MCP Tool Calling 版）。",
    url="http://localhost:5104",
    capabilities={"streaming": False, "memory": False},
    skills=[{"name": "analyze reviews and insights", "description": "检索评论和资料，提取用户痛点、好评点和卖点机会", "examples": ["分析家居小电器的用户评价和卖点"]}],
)

SYSTEM_PROMPT = """你是电商选品评论洞察 Agent。调用 MCP 工具后输出 JSON:
{
  "agent": "ReviewInsightAgent", "product_id": 商品ID, "status": "success",
  "scores": {"review_score": 0-100},
  "summary": "一句中文总结用户口碑和卖点",
  "details": {
    "positive_points": ["好评点"], "negative_points": ["差评点"], "pain_points": ["痛点"],
    "selling_point_opportunities": ["卖点机会"], "listing_copy_suggestions": ["文案建议"]
  },
  "suggestions": ["建议"], "error": null
}
只输出 JSON。"""

_executor = None


async def get_executor():
    global _executor
    if _executor is None:
        tools = await load_mcp_tools_from_url(REVIEW_MCP_URL)
        _executor = create_agent_executor(tools, SYSTEM_PROMPT)
        logger.info("ReviewInsightAgent MCP 工具加载完成: %d 个工具", len(tools))
    return _executor


async def handle_task(input_data: dict, task_logger) -> dict:
    product = input_data.get("product", {})
    constraints = input_data.get("constraints", {})
    product_id = product.get("product_id", 0)
    category = constraints.get("category") or product.get("category", "")
    product_name = product.get("product_name", "")

    query = f"""分析商品评论和口碑:
商品: {product_name} (ID={product_id}) 类目: {category}
先调用 get_review_statistics，再调用 search_reviews 和 search_product_documents，输出 JSON 分析结果。"""

    try:
        executor = await get_executor()
        return await format_query_result(query, executor, product_id, "ReviewInsightAgent")
    except Exception as e:
        logger.error("MCP Tool Calling ReviewInsightAgent 失败: %r", e)
        from prompts import REVIEW_INSIGHT_AGENT_SYSTEM_V1
        llm_output = await __import__("asyncio").to_thread(call_llm, REVIEW_INSIGHT_AGENT_SYSTEM_V1, json.dumps({"product": product, "constraints": constraints}, ensure_ascii=False))
        result = parse_json_from_llm(llm_output)
        result.setdefault("agent", "ReviewInsightAgent"); result.setdefault("product_id", product_id); result.setdefault("status", "success")
        return result


app = create_a2a_app(CARD, handle_task)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5104)
