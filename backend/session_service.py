"""
会话管理 + 追问管理
"""
from __future__ import annotations

import json

from sqlalchemy import text

from database import SessionLocal
from create_logger import get_logger
from schemas import IntentResult, UserIntent, FollowUp

logger = get_logger("session_service")

DEFAULT_CONTEXT = {
    "intent": "",
    "slots": {},
    "follow_up_count": 0,
    "last_query": "",
    "last_result_ids": [],
    "user_intent_snapshot": {},
}


class SessionManager:
    """会话管理器"""

    @staticmethod
    def get_or_create_session(session_id: str) -> dict:
        """获取或创建会话，返回 session 行 dict"""
        db = SessionLocal()
        try:
            row = db.execute(
                text("SELECT * FROM chat_sessions WHERE session_id = :sid"),
                {"sid": session_id},
            ).fetchone()

            if row:
                return {
                    "id": row[0],
                    "session_id": row[1],
                    "title": row[2],
                    "status": row[3],
                    "message_count": row[4],
                    "context_json": row[5] or "{}",
                    "created_at": str(row[6]) if row[6] else "",
                    "updated_at": str(row[7]) if row[7] else "",
                }

            # 创建新会话
            db.execute(
                text("INSERT INTO chat_sessions (session_id) VALUES (:sid)"),
                {"sid": session_id},
            )
            db.commit()
            return {
                "id": None,
                "session_id": session_id,
                "title": "新对话",
                "status": "active",
                "message_count": 0,
                "context_json": "{}",
                "created_at": "",
                "updated_at": "",
            }
        finally:
            db.close()

    @staticmethod
    def add_message(
        session_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        metadata: dict | None = None,
    ) -> None:
        """添加一条消息到会话"""
        db = SessionLocal()
        try:
            db.execute(
                text("""
                    INSERT INTO chat_messages (session_id, role, content, message_type, metadata)
                    VALUES (:sid, :role, :content, :mtype, :meta)
                """),
                {
                    "sid": session_id,
                    "role": role,
                    "content": content,
                    "mtype": message_type,
                    "meta": json.dumps(metadata, ensure_ascii=False) if metadata else None,
                },
            )
            db.execute(
                text("""
                    UPDATE chat_sessions
                    SET message_count = message_count + 1, updated_at = NOW()
                    WHERE session_id = :sid
                """),
                {"sid": session_id},
            )

            # 如果是用户首条消息，用前 20 字更新标题
            if role == "user":
                check = db.execute(
                    text("SELECT message_count FROM chat_sessions WHERE session_id = :sid"),
                    {"sid": session_id},
                ).fetchone()
                if check and check[0] == 1:
                    title = content[:20].replace("\n", " ")
                    db.execute(
                        text("UPDATE chat_sessions SET title = :t WHERE session_id = :sid"),
                        {"t": title, "sid": session_id},
                    )

            db.commit()
        finally:
            db.close()

    @staticmethod
    def get_history(session_id: str, limit: int = 20) -> list[dict]:
        """获取会话的历史消息"""
        db = SessionLocal()
        try:
            rows = db.execute(
                text("""
                    SELECT role, content, message_type, metadata, created_at
                    FROM chat_messages
                    WHERE session_id = :sid
                    ORDER BY created_at ASC
                    LIMIT :lim
                """),
                {"sid": session_id, "lim": limit},
            ).fetchall()

            return [
                {
                    "role": r[0],
                    "content": r[1],
                    "message_type": r[2],
                    "metadata": r[3],
                    "created_at": str(r[4]) if r[4] else "",
                }
                for r in rows
            ]
        finally:
            db.close()

    @staticmethod
    def update_context(session_id: str, context: dict) -> None:
        """更新会话上下文"""
        db = SessionLocal()
        try:
            db.execute(
                text("""
                    UPDATE chat_sessions
                    SET context_json = :ctx, updated_at = NOW()
                    WHERE session_id = :sid
                """),
                {
                    "sid": session_id,
                    "ctx": json.dumps(context, ensure_ascii=False),
                },
            )
            db.commit()
        finally:
            db.close()

    @staticmethod
    def list_sessions(session_ids: list[str] | None = None) -> list[dict]:
        """获取会话列表"""
        db = SessionLocal()
        try:
            if session_ids and len(session_ids) > 0:
                placeholders = ",".join([f":s{i}" for i in range(len(session_ids))])
                params = {f"s{i}": sid for i, sid in enumerate(session_ids)}
                rows = db.execute(
                    text(f"""
                        SELECT session_id, title, status, message_count, created_at, updated_at
                        FROM chat_sessions
                        WHERE session_id IN ({placeholders})
                        ORDER BY updated_at DESC
                    """),
                    params,
                ).fetchall()
            else:
                rows = db.execute(
                    text("""
                        SELECT session_id, title, status, message_count, created_at, updated_at
                        FROM chat_sessions
                        ORDER BY updated_at DESC
                        LIMIT 50
                    """),
                ).fetchall()

            return [
                {
                    "session_id": r[0],
                    "title": r[1],
                    "status": r[2],
                    "message_count": r[3],
                    "created_at": str(r[4]) if r[4] else "",
                    "updated_at": str(r[5]) if r[5] else "",
                }
                for r in rows
            ]
        finally:
            db.close()

    @staticmethod
    def delete_session(session_id: str) -> None:
        """删除会话及其消息"""
        db = SessionLocal()
        try:
            db.execute(text("DELETE FROM chat_messages WHERE session_id = :sid"), {"sid": session_id})
            db.execute(text("DELETE FROM chat_sessions WHERE session_id = :sid"), {"sid": session_id})
            db.commit()
        finally:
            db.close()

    @staticmethod
    def get_context(session_id: str) -> dict:
        """获取会话上下文"""
        session = SessionManager.get_or_create_session(session_id)
        try:
            return json.loads(session.get("context_json", "{}")) if session.get("context_json") else {}
        except (json.JSONDecodeError, TypeError):
            return {}


class FollowUpManager:
    """追问管理器"""

    MAX_FOLLOW_UP_COUNT = 3

    @staticmethod
    def should_follow_up(intent_result: IntentResult, context: dict) -> bool:
        """判断是否需要追问"""
        follow_up_count = context.get("follow_up_count", 0)
        if follow_up_count >= FollowUpManager.MAX_FOLLOW_UP_COUNT:
            return False
        if not intent_result.slots_missing:
            return False
        return True

    @staticmethod
    def generate_follow_up(
        intent_result: IntentResult,
        context: dict,
        user_intent: UserIntent | None = None,
    ) -> FollowUp:
        """生成追问消息"""
        missing = intent_result.slots_missing

        if not missing:
            return FollowUp()

        # 根据第一个缺失槽位生成追问
        slot = missing[0]
        question, options = _follow_up_for_slot(slot, user_intent, context)

        return FollowUp(
            question=question,
            options=options,
            missing_slots=missing,
        )

    @staticmethod
    def merge_slot_reply(
        context: dict,
        user_reply: str,
        intent_result: IntentResult,
    ) -> dict:
        """将用户回复合并到上下文槽位中"""
        slots = context.get("slots", {})
        new_slots = intent_result.slots

        for key, val in new_slots.items():
            if val is not None and val != "" and (isinstance(val, list) and len(val) > 0 or not isinstance(val, list) and val):
                slots[key] = val

        # 更新上下文
        return {
            **context,
            "slots": slots,
            "follow_up_count": context.get("follow_up_count", 0) + 1,
            "last_query": user_reply,
        }


def _follow_up_for_slot(
    slot: str,
    user_intent: UserIntent | None,
    context: dict,
) -> tuple[str, list[str]]:
    """根据槽位和用户意图生成追问文案"""

    intent_label = user_intent.experience_level if user_intent else "intermediate"

    templates = {
        "category": {
            "newbie": ("请问您想选哪个类目的产品？我帮您看看入门款。", ["家居", "数码配件", "服饰", "美妆", "其他"]),
            "default": ("请问您想选哪个类目的产品？", ["家居", "数码配件", "服饰", "美妆", "玩具", "其他"]),
        },
        "price_min": {
            "default": ("您的预算从多少开始？", ["50", "100", "200", "不限"]),
        },
        "price_max": {
            "newbie": ("预算上限是多少？新手建议先控制在200以内。", ["100", "200", "300", "500", "不限"]),
            "default": ("预算上限是多少？", ["200", "300", "500", "1000", "不限"]),
        },
        "season": {
            "default": ("这是针对哪个季节或活动场景的选品？", ["春季", "夏季", "秋季", "冬季", "日常", "不限"]),
        },
        "preferences": {
            "newbie": ("对商品有什么特别偏好吗？我帮您筛好做的。", ["低门槛", "好评多", "退货少", "不限"]),
            "default": ("对商品有什么特别偏好吗？", ["高利润", "低竞争", "品质好", "走量快", "不限"]),
        },
        "target_product_ids": {
            "default": ("请问您想对比哪几个商品？可以告诉我商品名称或ID。", []),
        },
        "profit_requirement": {
            "newbie": ("对利润的要求如何？新手建议先追求稳定。", ["中等(20-30%)", "尽量高", "先不管"]),
            "default": ("目标利润率大概多少？", ["20%以上", "30%以上", "越高越好"]),
        },
    }

    slot_templates = templates.get(slot, {"default": (f"请补充信息：{slot}", [])})

    if intent_label in slot_templates:
        return slot_templates[intent_label]
    return slot_templates["default"]
