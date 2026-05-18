"""
统一 MCP Client Manager — 管理多个 MCP Server 连接

支持:
  - 同时连接 Browser / Filesystem / Custom MCP servers
  - 按 Agent 分配工具集
  - 连接池复用
  - 工具加载缓存
  - Docker 环境自动适配 (通过环境变量覆盖 URL)

架构:
  Agent
    → MCPClientManager.get_tools_for_agent("MarketAgent")
      → [amzn_search, amzn_product, query_market_trends, ...]
    → LangGraph ReAct Agent 调用工具
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from create_logger import get_logger

logger = get_logger("mcp_client_manager")

# ── Docker 环境 MCP URL 覆盖 ──────────────────────


def _url(key: str, default: str) -> str:
    return os.getenv(key, default)


# ── MCP Server 注册表 ───────────────────────────────

@dataclass
class MCPServerConfig:
    name: str
    url: str
    description: str = ""
    enabled: bool = True


MCP_SERVER_REGISTRY: dict[str, MCPServerConfig] = {
    # ── 自定义业务 MCP (已有) ────────────────────
    "market_mcp": MCPServerConfig(
        name="Market MCP",
        url=_url("MARKET_MCP_URL", "http://localhost:8101/mcp"),
        description="市场趋势、竞品分析、价格带",
    ),
    "profit_mcp": MCPServerConfig(
        name="Profit MCP",
        url=_url("PROFIT_MCP_URL", "http://localhost:8102/mcp"),
        description="利润测算、建议售价、盈亏平衡",
    ),
    "supply_risk_mcp": MCPServerConfig(
        name="Supply Risk MCP",
        url=_url("SUPPLY_RISK_MCP_URL", "http://localhost:8103/mcp"),
        description="供应商查询、风险评估、备货建议",
    ),
    "review_mcp": MCPServerConfig(
        name="Review MCP",
        url=_url("REVIEW_MCP_URL", "http://localhost:8104/mcp"),
        description="评论检索 (Milvus)、评论统计",
    ),
    # ── 新增 MCP (v3.0) ──────────────────────────
    "browser_mcp": MCPServerConfig(
        name="Browser MCP",
        url=_url("BROWSER_MCP_URL", "http://localhost:8201/mcp"),
        description="Amazon 搜索/商品详情/评论抓取 (Playwright)",
    ),
    "filesystem_mcp": MCPServerConfig(
        name="Filesystem MCP",
        url=_url("FILESYSTEM_MCP_URL", "http://localhost:8202/mcp"),
        description="CSV/JSON/文本文件读取",
    ),
}

# ── Agent → MCP Server 映射 ─────────────────────────

AGENT_MCP_MAP: dict[str, list[str]] = {
    "MarketAgent": [
        "market_mcp",       # 市场趋势 + 竞品
        "browser_mcp",      # Amazon 实时搜索增强
    ],
    "ProfitAgent": [
        "profit_mcp",       # 利润测算
    ],
    "SupplyRiskAgent": [
        "supply_risk_mcp",  # 供应商 + 风险
    ],
    "ReviewInsightAgent": [
        "review_mcp",         # Milvus 评论检索
        "browser_mcp",        # Amazon 评论抓取 (补充)
        "filesystem_mcp",     # 本地 CSV/JSON 评论数据
    ],
}

# ── 全局工具缓存 ────────────────────────────────────

_tools_cache: dict[str, list] = {}    # key: server_name → tools


class MCPClientManager:
    """统一 MCP 客户端管理器"""

    @staticmethod
    async def load_tools_for_agent(
        agent_name: str,
        extra_servers: list[str] | None = None,
    ) -> list:
        """
        为一个 Agent 加载它需要的所有 MCP 工具。

        返回: LangChain Tool 列表，可直接传给 create_react_agent
        """
        server_names = AGENT_MCP_MAP.get(agent_name, ["market_mcp"])
        if extra_servers:
            server_names = list(dict.fromkeys(server_names + extra_servers))

        all_tools = []
        for sname in server_names:
            config = MCP_SERVER_REGISTRY.get(sname)
            if config is None or not config.enabled:
                continue

            try:
                tools = await MCPClientManager._load_from_server(sname, config.url)
                all_tools.extend(tools)
                logger.info("Agent=%s 加载 MCP: %s (%d tools)", agent_name, sname, len(tools))
            except Exception as e:
                logger.warning("Agent=%s MCP %s 加载失败: %s", agent_name, sname, e)

        return all_tools

    @staticmethod
    async def load_all_tools() -> dict[str, list]:
        """加载所有已注册 MCP Server 的工具 (用于全局初始化)"""
        result = {}
        for sname, config in MCP_SERVER_REGISTRY.items():
            if not config.enabled:
                continue
            try:
                tools = await MCPClientManager._load_from_server(sname, config.url)
                result[sname] = tools
                logger.info("MCP %s 加载完成: %d tools", sname, len(tools))
            except Exception as e:
                logger.warning("MCP %s 加载失败: %s", sname, e)
                result[sname] = []
        return result

    @staticmethod
    async def _load_from_server(server_name: str, url: str) -> list:
        """从单个 MCP Server 加载工具列表 (带缓存)"""
        if server_name in _tools_cache:
            return _tools_cache[server_name]

        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
        from langchain_mcp_adapters.tools import load_mcp_tools

        clean_url = url.rstrip("/")
        async with streamablehttp_client(clean_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await load_mcp_tools(session)
                _tools_cache[server_name] = tools
                return tools

    @staticmethod
    def clear_cache():
        _tools_cache.clear()

    @staticmethod
    def get_agent_mcp_config(agent_name: str) -> dict[str, MCPServerConfig]:
        """获取某 Agent 关联的所有 MCP Server 配置"""
        server_names = AGENT_MCP_MAP.get(agent_name, ["market_mcp"])
        return {
            name: MCP_SERVER_REGISTRY[name]
            for name in server_names
            if name in MCP_SERVER_REGISTRY and MCP_SERVER_REGISTRY[name].enabled
        }

    @staticmethod
    def override_urls(overrides: dict[str, str]):
        """批量覆盖 MCP Server URL (Docker 环境用)"""
        for sname, url in overrides.items():
            if sname in MCP_SERVER_REGISTRY:
                MCP_SERVER_REGISTRY[sname].url = url
