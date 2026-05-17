import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import API_PORT
from create_logger import get_logger

logger = get_logger("api_server")

app = FastAPI(title="ProductScout A2A", version="0.1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """服务启动时初始化记忆系统 DB 连接并加载持久化数据。"""
    try:
        import mysql.connector
        from config import MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE
        from memory import ConversationMemory
        from session_orchestrator import _get_memory, _session_memories

        db_conn = mysql.connector.connect(
            host=MYSQL_HOST, port=MYSQL_PORT,
            user=MYSQL_USER, password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
        )
        # 恢复已有会话的记忆（最近 50 个 session）
        from session_service import SessionManager
        recent_sessions = SessionManager.list_sessions()[:50]
        restored_count = 0
        for s in recent_sessions:
            sid = s["session_id"]
            memory = _get_memory(sid)
            memory.set_db_connection(db_conn)
            memory.load_all_from_db()
            restored_count += 1

        logger.info("记忆系统初始化完成: DB OK, 恢复 %d 个会话记忆", restored_count)
    except Exception as e:
        logger.warning("记忆系统 DB 连接失败（不影响主流程）: %s", e)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ProductScout A2A"}


# ── Selection routes ─────────────────────────────────
from api_routes.selection import router as selection_router
app.include_router(selection_router, prefix="/api/selection", tags=["selection"])

# ── Chat routes ──────────────────────────────────────
from api_routes.chat import router as chat_router
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])


if __name__ == "__main__":
    logger.info("Starting ProductScout A2A API on port %d", API_PORT)
    uvicorn.run("api_server:app", host="0.0.0.0", port=API_PORT, reload=False)
