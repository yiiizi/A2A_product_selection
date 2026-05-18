"""
A2A ReAct Agent 共享基座 — MCP 标准协议版

提供:
  1. MCP 工具加载 — 通过 streamablehttp_client + load_mcp_tools() 加载 MCP Server 工具
  2. Agent 工厂 — 基于 langgraph 创建 ReAct Agent
  3. 结果解析 — 从 Agent 输出中提取 JSON
"""
from __future__ import annotations

import json
from typing import Any

from langchain_openai import ChatOpenAI

from config import API_KEY, BASE_URL, LLM_MODEL, LLM_TEMPERATURE

# ── MCP 工具加载（带缓存）─────────────────────────────

_tools_cache: dict[str, list] = {}


async def load_mcp_tools_from_url(mcp_url: str) -> list:
    """通过 MCP streamable-http 协议连接 MCP Server 并加载工具列表。

    结果按 URL 缓存，多次调用仅首次建立 MCP 会话。
    """
    if mcp_url in _tools_cache:
        return _tools_cache[mcp_url]

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from langchain_mcp_adapters.tools import load_mcp_tools

    url = mcp_url.rstrip("/")
    try:
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await load_mcp_tools(session)
                _tools_cache[mcp_url] = tools
                return tools
    except Exception:
        # MCP Server 不可用时返回空列表，不中断 Agent 启动
        return []


async def load_mcp_tools_for_agent(agent_name: str) -> list:
    """为一个 Agent 加载其需要的所有 MCP Server 的工具。

    使用 mcp_client_manager 的映射配置。
    这是推荐的加载方式——Agent 不需要知道具体 MCP URL。
    """
    try:
        from mcp_client_manager import MCPClientManager
        return await MCPClientManager.load_tools_for_agent(agent_name)
    except ImportError:
        # 降级: 如果没有 mcp_client_manager, 返回空
        return []
    except Exception:
        return []


# ── Agent 工厂 ──────────────────────────────────────

_llm: ChatOpenAI | None = None


def get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            api_key=API_KEY,
            base_url=BASE_URL,
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
        )
    return _llm


def create_agent_executor(tools: list, system_prompt: str):
    """基于 langgraph.prebuilt.create_react_agent 创建 Agent。"""
    from langgraph.prebuilt import create_react_agent

    llm = get_llm()
    return create_react_agent(llm, tools, prompt=system_prompt)


def parse_agent_output(output: str) -> dict:
    """从 Agent 文本输出中提取 JSON"""
    text = output.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    return {"summary": text[:500], "scores": {}, "details": {}, "suggestions": []}


def _extract_last_message(result: dict) -> str:
    """从 langgraph agent 结果中提取最后一条 AI 消息文本"""
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if hasattr(msg, "content") and msg.type == "ai":
            content = msg.content
            if isinstance(content, str) and content.strip():
                return content
    return str(result.get("messages", []))


async def format_query_result(query: str, agent, product_id: int, agent_name: str) -> dict:
    """执行 Agent 查询并格式化为 AgentResult 兼容格式"""
    result = await agent.ainvoke({"messages": [{"role": "user", "content": query}]})
    output = _extract_last_message(result)
    parsed = parse_agent_output(output)

    return {
        "agent": agent_name,
        "product_id": product_id,
        "status": "success",
        "scores": parsed.get("scores", {}),
        "summary": parsed.get("summary", "") or output[:300],
        "details": parsed.get("details", {}),
        "suggestions": parsed.get("suggestions", []),
        "error": None,
    }
