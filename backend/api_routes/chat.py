from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from create_logger import get_logger
from schemas import ChatMessage, ChatRequest, ChatResponse
from session_service import SessionManager

logger = get_logger("api_chat")
router = APIRouter()


@router.post("/send")
async def send_message(request: ChatRequest):
    try:
        from session_orchestrator import handle_message

        return await handle_message(request)
    except Exception as exc:
        logger.exception("聊天接口处理失败")
        return ChatResponse(
            session_id=request.session_id,
            message=ChatMessage(
                role="assistant",
                content=f"请求处理失败：{exc}",
                message_type="text",
            ),
        )


@router.post("/stream")
async def stream_message(request: ChatRequest):
    from session_orchestrator import _event, stream_message as stream_orchestrator

    async def event_generator():
        try:
            async for item in stream_orchestrator(request):
                yield _event(item["event"], item["data"])
        except Exception as exc:
            logger.exception("流式聊天处理失败")
            yield _event("error", {"message": f"流式处理失败：{exc}"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions")
async def list_sessions(ids: str = ""):
    try:
        session_ids = [s.strip() for s in ids.split(",") if s.strip()] if ids else None
        data = SessionManager.list_sessions(session_ids)
        return {"status": "success", "data": data}
    except Exception as exc:
        logger.exception("查询会话列表失败")
        return {"status": "error", "message": str(exc)}


@router.post("/sessions")
async def create_session():
    session_id = uuid.uuid4().hex
    SessionManager.get_or_create_session(session_id)
    return {"status": "success", "session_id": session_id}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session = SessionManager.get_or_create_session(session_id)
    history = SessionManager.get_history(session_id)
    return {
        "status": "success",
        "data": {
            "session": session,
            "history": history,
        },
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    SessionManager.delete_session(session_id)
    return {"status": "success", "message": "删除成功"}
