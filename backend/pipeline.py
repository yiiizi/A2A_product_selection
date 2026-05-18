from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from langgraph_selection_workflow import run_selection_graph, stream_selection_graph


async def run_full_pipeline(
    user_query: str,
    top_k: int = 5,
    pre_slots: dict | None = None,
    pre_intent: str | None = None,
    pre_user_intent=None,
) -> dict[str, Any]:
    """Compatibility wrapper for the LangGraph selection workflow."""
    return await run_selection_graph(
        user_query=user_query,
        top_k=top_k,
        pre_slots=pre_slots,
        pre_intent=pre_intent,
        pre_user_intent=pre_user_intent,
    )


async def stream_full_pipeline(
    user_query: str,
    top_k: int,
    pre_intent: str,
    pre_slots: dict,
    pre_user_intent,
    context: dict | None = None,
) -> AsyncGenerator[dict, None]:
    """Compatibility wrapper for SSE streaming from the LangGraph workflow."""
    async for event in stream_selection_graph(
        user_query=user_query,
        top_k=top_k,
        pre_intent=pre_intent,
        pre_slots=pre_slots,
        pre_user_intent=pre_user_intent,
        context=context,
    ):
        yield event
