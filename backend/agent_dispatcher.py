"""
Agent Dispatcher — 优先级调度 + 超时控制 + 失败降级 + MCP 缓存。

设计目标:
  - 高优先级 Agent (priority=1) 先并行执行
  - 低优先级 Agent (priority>1) 串行执行 (可选依赖高优结果)
  - 单个 Agent 失败不影响其他 Agent
  - 请求级 MCP 结果缓存，避免同一请求内重复查询
  - MCP 大结果自动截断，减少 LLM context token 消耗
"""

from __future__ import annotations

import asyncio
from typing import Any

from create_logger import get_logger

logger = get_logger("agent_dispatcher")

# ── 并发控制 ─────────────────────────────────────────

MCP_SEMAPHORE = asyncio.Semaphore(8)
AGENT_SEMAPHORE = asyncio.Semaphore(4)

# ── Agent 超时配置 ───────────────────────────────────

AGENT_TIMEOUTS: dict[str, int] = {
    "MarketAgent": 90,
    "ProfitAgent": 60,
    "SupplyRiskAgent": 60,
    "ReviewInsightAgent": 90,
}

DEFAULT_AGENT_TIMEOUT = 120

# ── MCP 结果缓存 (请求级) ────────────────────────────

_mcp_cache: dict[str, dict] = {}


def clear_mcp_cache():
    """每次请求开始前清空 MCP 缓存"""
    _mcp_cache.clear()


def cached_mcp_call(tool_name: str, params_key: str, fetch_fn) -> dict:
    """
    请求级 MCP 结果缓存。

    参数:
        tool_name: 工具名
        params_key: 参数的 JSON 字符串 (作为 cache key)
        fetch_fn: 异步函数，无缓存时调用
    """
    cache_key = f"{tool_name}:{params_key}"
    if cache_key in _mcp_cache:
        logger.debug("MCP cache 命中: %s", cache_key)
        return _mcp_cache[cache_key]
    return None


def set_mcp_cache(tool_name: str, params_key: str, result: dict):
    cache_key = f"{tool_name}:{params_key}"
    _mcp_cache[cache_key] = result


# ── 结果截断 ─────────────────────────────────────────

def compact_mcp_result(raw_data: dict, max_list_items: int = 5) -> dict:
    """
    截断 MCP 返回的大列表，保留统计摘要 + 前 N 条。
    减少传入 LLM 的 token 量。
    """
    if not isinstance(raw_data, dict):
        return raw_data

    result: dict[str, Any] = {}
    for key, value in raw_data.items():
        if isinstance(value, list) and len(value) > max_list_items:
            result[key] = value[:max_list_items]
            result[f"{key}_total"] = len(value)
        elif isinstance(value, dict) and _dict_depth(value) > 3:
            result[key] = str(value)[:500]
        else:
            result[key] = value
    return result


def _dict_depth(d: dict) -> int:
    if not isinstance(d, dict):
        return 0
    depths = [0]
    for v in d.values():
        if isinstance(v, dict):
            depths.append(1 + _dict_depth(v))
    return max(depths)


# ── 调度核心 ─────────────────────────────────────────

async def dispatch_agents(
    agents: dict,
    candidates: list[dict],
    constraints,
    user_query: str,
    analyze_fn,
) -> list[Any]:
    """
    核心调度: 优先级分组 → 并行执行 → 结果聚合。

    参数:
        agents: {agent_name: AgentConfig}
        candidates: 候选商品列表
        constraints: Constraints 对象
        user_query: 用户原始查询
        analyze_fn: async (product, constraints, query, agents) → ProductAnalysisResult

    返回:
        排序后的 ProductAnalysisResult 列表
    """
    if not agents:
        return []

    # 分组
    high_pri = {n: c for n, c in agents.items() if getattr(c, "priority", 1) == 1}
    low_pri = {n: c for n, c in agents.items() if getattr(c, "priority", 1) > 1}

    all_results: dict[str, list] = {}

    # 高优先级并行
    if high_pri:
        logger.info("高优先级 Agent 并行: %s", list(high_pri.keys()))
        hp_results = await _execute_product_batch(
            high_pri, candidates, constraints, user_query, analyze_fn,
        )
        all_results.update(hp_results)

    # 低优先级串行
    for name, config in low_pri.items():
        logger.info("低优先级 Agent 串行: %s", name)
        single = {name: config}
        lp_results = await _execute_product_batch(
            single, candidates[:1], constraints, user_query, analyze_fn,  # 低优先级只分析第一个
        )
        all_results.update(lp_results)

    return all_results


async def _execute_product_batch(
    agents: dict,
    candidates: list[dict],
    constraints,
    user_query: str,
    analyze_fn,
) -> dict[str, list]:
    """对每个候选商品并行调 Agent 组"""

    products_by_agent: dict[str, list] = {name: [] for name in agents}

    for product in candidates:
        timeout = _get_max_timeout(agents)
        try:
            async with AGENT_SEMAPHORE:
                result = await asyncio.wait_for(
                    analyze_fn(product, constraints, user_query, agents=agents),
                    timeout=timeout,
                )
            for agent_name in agents:
                agent_result = result.agent_results.get(agent_name)
                if agent_result:
                    products_by_agent[agent_name].append({
                        "product_id": product["product_id"],
                        "status": agent_result.status,
                        "scores": agent_result.scores,
                        "summary": agent_result.summary,
                    })
        except asyncio.TimeoutError:
            logger.warning("Agent 组超时 (%.0fs): %s 商品=%s", timeout, list(agents.keys()), product.get("product_name"))
            for agent_name in agents:
                products_by_agent[agent_name].append({
                    "product_id": product["product_id"],
                    "status": "failed",
                    "error": f"超时 ({timeout}s)",
                })
        except Exception as e:
            logger.error("Agent 组异常: %s 商品=%s: %s", list(agents.keys()), product.get("product_name"), e)
            for agent_name in agents:
                products_by_agent[agent_name].append({
                    "product_id": product["product_id"],
                    "status": "failed",
                    "error": str(e),
                })

    return products_by_agent


def _get_max_timeout(agents: dict) -> int:
    return max(
        (AGENT_TIMEOUTS.get(name, DEFAULT_AGENT_TIMEOUT) for name in agents),
        default=DEFAULT_AGENT_TIMEOUT,
    )
