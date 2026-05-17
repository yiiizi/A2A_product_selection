"""
四组件记忆管理器 — 支持 MySQL 持久化和服务重启恢复

组件:
  1. short_term_messages — 最近 N 轮对话
  2. user_preferences    — 用户偏好 (键值对)
  3. current_task        — 当前任务上下文
  4. query_history       — 历史查询记录
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytz

from create_logger import get_logger

logger = get_logger("memory")

TZ = pytz.timezone("Asia/Shanghai")


class ConversationMemory:
    """四组件记忆管理器"""

    def __init__(self, short_term_limit: int = 10):
        self.short_term_messages: list[dict] = []
        self.user_preferences: dict[str, str] = {}
        self.current_task: dict[str, Any] = {}
        self.query_history: list[dict] = []
        self.short_term_limit = short_term_limit
        self._db_conn = None

    # ── DB 连接 ─────────────────────────────────────

    def set_db_connection(self, db_conn):
        self._db_conn = db_conn

    def _ensure_db(self):
        if self._db_conn is None:
            return False
        try:
            self._db_conn.ping(reconnect=True)
            return True
        except Exception:
            return False

    # ── 短期对话 ────────────────────────────────────

    def add_message(self, role: str, content: str):
        self.short_term_messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(TZ).strftime("%H:%M:%S"),
        })
        if len(self.short_term_messages) > self.short_term_limit:
            self.short_term_messages = self.short_term_messages[-self.short_term_limit:]
        self.save_messages_to_db()

    def get_short_term_text(self) -> str:
        if not self.short_term_messages:
            return "暂无对话历史"
        lines = []
        for msg in self.short_term_messages:
            label = "用户" if msg["role"] == "user" else "助手"
            lines.append(f"{label}: {msg['content']}")
        return "\n".join(lines)

    # ── 用户偏好 ────────────────────────────────────

    def update_preferences(self, prefs: dict):
        self.user_preferences.update({k: str(v) for k, v in prefs.items()})
        self.save_preferences_to_db()

    def get_preference_text(self) -> str:
        if not self.user_preferences:
            return "无已知的用户偏好"
        return "，".join(f"{k}: {v}" for k, v in self.user_preferences.items())

    # ── 任务上下文 ──────────────────────────────────

    def update_task_context(self, ctx: dict):
        self.current_task.update(ctx)

    def clear_task_context(self):
        self.current_task = {}

    # ── 查询历史 ────────────────────────────────────

    def add_query(self, intent_type: str, query: str):
        self.query_history.append({
            "type": intent_type,
            "query": query,
            "timestamp": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
        })
        if len(self.query_history) > 20:
            self.query_history = self.query_history[-20:]
        self.save_query_to_db(intent_type, query)

    # ── 序列化 ──────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "short_term_messages": self.short_term_messages,
            "user_preferences": self.user_preferences,
            "current_task": self.current_task,
            "query_history": self.query_history[-5:],
        }

    def clear(self):
        self.short_term_messages = []
        self.user_preferences = {}
        self.current_task = {}
        self.query_history = []
        self.clear_all_from_db()

    # ═════════════════════════════════════════════════
    #  MySQL 持久化
    # ═════════════════════════════════════════════════

    def save_messages_to_db(self):
        if not self._ensure_db():
            return
        try:
            cursor = self._db_conn.cursor()
            cursor.execute("DELETE FROM system_memory")
            for i, msg in enumerate(self.short_term_messages):
                cursor.execute(
                    "INSERT INTO system_memory (role, content, message_time, message_order) "
                    "VALUES (%s, %s, %s, %s)",
                    (msg["role"], msg["content"], msg["timestamp"], i),
                )
            self._db_conn.commit()
            cursor.close()
        except Exception as e:
            logger.warning("保存短期对话失败: %s", e)

    def load_messages_from_db(self):
        if not self._ensure_db():
            return
        try:
            cursor = self._db_conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT role, content, message_time FROM system_memory ORDER BY message_order ASC"
            )
            rows = cursor.fetchall()
            cursor.close()
            self.short_term_messages = [
                {"role": r["role"], "content": r["content"], "timestamp": r["message_time"]}
                for r in rows
            ]
        except Exception as e:
            logger.warning("加载短期对话失败: %s", e)

    def save_preferences_to_db(self):
        if not self._ensure_db():
            return
        try:
            cursor = self._db_conn.cursor()
            for key, value in self.user_preferences.items():
                cursor.execute(
                    "INSERT INTO user_preferences (pref_key, pref_value) "
                    "VALUES (%s, %s) ON DUPLICATE KEY UPDATE pref_value = %s",
                    (key, str(value), str(value)),
                )
            self._db_conn.commit()
            cursor.close()
        except Exception as e:
            logger.warning("保存用户偏好失败: %s", e)

    def load_preferences_from_db(self):
        if not self._ensure_db():
            return
        try:
            cursor = self._db_conn.cursor(dictionary=True)
            cursor.execute("SELECT pref_key, pref_value FROM user_preferences")
            rows = cursor.fetchall()
            cursor.close()
            self.user_preferences = {r["pref_key"]: r["pref_value"] for r in rows}
        except Exception as e:
            logger.warning("加载用户偏好失败: %s", e)

    def save_query_to_db(self, intent_type: str, query: str):
        if not self._ensure_db():
            return
        try:
            cursor = self._db_conn.cursor()
            cursor.execute(
                "INSERT INTO query_history (intent_type, query_content, query_time) "
                "VALUES (%s, %s, %s)",
                (intent_type, json.dumps({"query": query}, ensure_ascii=False), datetime.now(TZ)),
            )
            self._db_conn.commit()
            cursor.close()
        except Exception as e:
            logger.warning("保存查询历史失败: %s", e)

    def load_queries_from_db(self, limit: int = 20):
        if not self._ensure_db():
            return
        try:
            cursor = self._db_conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT intent_type, query_content, query_time FROM query_history "
                "ORDER BY query_time DESC LIMIT %s",
                (limit,),
            )
            rows = cursor.fetchall()
            cursor.close()
            rows.reverse()
            self.query_history = []
            for r in rows:
                try:
                    qd = json.loads(r["query_content"])
                    qtext = qd.get("query", "")
                except Exception:
                    qtext = ""
                self.query_history.append({
                    "type": r["intent_type"],
                    "query": qtext,
                    "timestamp": r["query_time"].strftime("%Y-%m-%d %H:%M:%S") if r["query_time"] else "",
                })
        except Exception as e:
            logger.warning("加载查询历史失败: %s", e)

    def load_all_from_db(self):
        self.load_messages_from_db()
        self.load_preferences_from_db()
        self.load_queries_from_db()
        logger.info(
            "记忆加载完成: 偏好=%d项, 历史=%d条, 对话=%d条",
            len(self.user_preferences),
            len(self.query_history),
            len(self.short_term_messages),
        )

    def clear_all_from_db(self):
        if not self._ensure_db():
            return
        try:
            cursor = self._db_conn.cursor()
            cursor.execute("DELETE FROM system_memory")
            cursor.execute("DELETE FROM query_history")
            cursor.execute("DELETE FROM user_preferences")
            self._db_conn.commit()
            cursor.close()
        except Exception as e:
            logger.warning("清空数据库记忆失败: %s", e)
