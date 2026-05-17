"""
A2A 协议基座模块。
提供 Agent Card、Task 处理、LLM 调用等共享能力。
"""

from __future__ import annotations

import json
import time
from enum import Enum
from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field
from openai import OpenAI

from config import (
    API_KEY, BASE_URL, LLM_MODEL, LLM_TEMPERATURE,
    LLM_ENABLE_THINKING, MCP_TIMEOUT_SECONDS, MOCK_LLM,
)
from create_logger import get_logger


# ── A2A 协议模型 ─────────────────────────────────────

class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"


class Message(BaseModel):
    role: str = "user"
    parts: list[dict[str, Any]] = Field(default_factory=list)


class TaskSendParams(BaseModel):
    id: str = ""
    message: Message


class TaskSendRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str = "tasks/send"
    params: TaskSendParams
    id: int = 1


class Artifact(BaseModel):
    name: str = "result"
    parts: list[dict[str, Any]] = Field(default_factory=list)


class TaskResult(BaseModel):
    id: str
    status: TaskState
    artifacts: list[Artifact] = Field(default_factory=list)
    error: str | None = None


class TaskSendResponse(BaseModel):
    jsonrpc: str = "2.0"
    result: TaskResult
    id: int = 1


# ── Agent Card ───────────────────────────────────────

class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    version: str = "1.0.0"
    capabilities: dict[str, bool] = Field(default_factory=lambda: {"streaming": False, "memory": False})
    skills: list[dict[str, Any]] = Field(default_factory=list)


# ── LLM 工具 ─────────────────────────────────────────

_llm_client: OpenAI | None = None


def get_llm_client() -> OpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _llm_client


def call_llm(system_prompt: str, user_content: str) -> str:
    """调用 LLM 获取响应。"""
    if MOCK_LLM:
        return '{"details": {}, "suggestions": [], "summary": "[MOCK] LLM summary"}'

    client = get_llm_client()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    return response.choices[0].message.content or ""


def parse_json_from_llm(text: str) -> dict:
    """从 LLM 输出中提取 JSON。"""
    # 清理 markdown code block
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # 去掉第一行和最后一行的 ```
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 尝试找到第一个 { 和最后一个 }
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass
    return {}


# ── MCP 调用 ─────────────────────────────────────────

_mcp_client: httpx.AsyncClient | None = None


def get_mcp_client() -> httpx.AsyncClient:
    """获取全局 MCP HTTP 客户端（连接池复用，避免每次调用建立 TCP 连接）。"""
    global _mcp_client
    if _mcp_client is None or _mcp_client.is_closed:
        _mcp_client = httpx.AsyncClient(
            timeout=MCP_TIMEOUT_SECONDS,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        )
    return _mcp_client


async def call_mcp_tool(mcp_url: str, tool_name: str, params: dict) -> dict:
    """调用 MCP 工具（复用全局连接池）。"""
    base_url = mcp_url.rstrip("/")
    if base_url.endswith("/mcp"):
        base_url = base_url[:-4]
    url = f"{base_url}/tools/{tool_name}"
    client = get_mcp_client()
    resp = await client.post(url, json=params)
    resp.raise_for_status()
    return resp.json()


# ── Task 存储 ────────────────────────────────────────

_tasks: dict[str, TaskResult] = {}


def get_task(task_id: str) -> TaskResult | None:
    return _tasks.get(task_id)


def save_task(task: TaskResult):
    _tasks[task.id] = task


# ── 创建 A2A App ─────────────────────────────────────

def create_a2a_app(card: AgentCard, handler) -> FastAPI:
    """创建标准 A2A Agent FastAPI 应用（兼容旧版）。"""
    logger = get_logger(card.name)
    app = FastAPI(title=card.name, version=card.version)

    @app.get("/.well-known/agent.json")
    async def get_agent_card():
        return card.model_dump()

    @app.post("/tasks/send")
    async def send_task(req: TaskSendRequest):
        task_id = req.params.id or f"task-{int(time.time() * 1000)}"
        logger.info("收到 Task: %s", task_id)

        task = TaskResult(id=task_id, status=TaskState.WORKING)
        save_task(task)

        try:
            content = ""
            for part in req.params.message.parts:
                if "text" in part:
                    content = part["text"]
                    break

            input_data = json.loads(content) if content else {}
            result = await handler(input_data, logger)

            artifact = Artifact(
                name="result",
                parts=[{"text": json.dumps(result, ensure_ascii=False)}],
            )
            task.status = TaskState.COMPLETED
            task.artifacts = [artifact]
            save_task(task)

            logger.info("Task %s 完成", task_id)
            return TaskSendResponse(result=task)

        except Exception as e:
            logger.error("Task %s 失败: %s", task_id, str(e))
            task.status = TaskState.FAILED
            task.error = str(e)
            save_task(task)
            return TaskSendResponse(result=task)

    @app.get("/tasks/{task_id}")
    async def get_task_status(task_id: str):
        task = get_task(task_id)
        if not task:
            return {"error": "Task not found"}
        return task.model_dump()

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": card.name}

    return app


# ── python_a2a 集成 ─────────────────────────────────

_HAS_PYTHON_A2A = False
try:
    from python_a2a import A2AServer, AgentCard as P2ACard, AgentSkill, Task, TaskStatus, TaskState as P2ATaskState
    from python_a2a import Message as P2AMessage, MessageRole, TextContent
    _HAS_PYTHON_A2A = True
except ImportError:
    pass


def convert_card_to_p2a(card: AgentCard):
    """将自定义 AgentCard 转为 python_a2a AgentCard"""
    if not _HAS_PYTHON_A2A:
        return None
    skills = []
    for s in card.skills:
        skills.append(AgentSkill(
            name=s.get("name", ""),
            description=s.get("description", ""),
            examples=s.get("examples", []),
        ))
    return P2ACard(
        name=card.name,
        description=card.description,
        url=card.url,
        version=card.version,
        capabilities=card.capabilities,
        skills=skills,
    )


def create_python_a2a_app(card: AgentCard, handler):
    """创建基于 python_a2a 的 A2A Server。
    同时保留旧版的 /.well-known/agent.json 和 /tasks/send 兼容端点。
    """
    if not _HAS_PYTHON_A2A:
        logger = get_logger(card.name)
        logger.warning("python_a2a 未安装，降级为自定义 A2A 协议")
        return create_a2a_app(card, handler)

    logger = get_logger(card.name)
    p2a_card = convert_card_to_p2a(card)

    class AppA2AServer(A2AServer):
        def __init__(self):
            super().__init__(agent_card=p2a_card)

        async def handle_task(self, task: Task) -> Task:
            try:
                text = ""
                if task.messages:
                    for msg in reversed(task.messages):
                        if hasattr(msg, 'content') and isinstance(msg.content, str):
                            text = msg.content
                            break
                input_data = json.loads(text) if text else {}
                result = await handler(input_data, logger)
                return Task(
                    id=task.id,
                    session_id=task.session_id,
                    status=TaskStatus(state=P2ATaskState.COMPLETED),
                    artifacts=[{"name": "result", "parts": [{"text": json.dumps(result, ensure_ascii=False)}]}],
                )
            except Exception as e:
                logger.error("Task 失败: %s", e)
                return Task(
                    id=task.id,
                    session_id=task.session_id,
                    status=TaskStatus(state=P2ATaskState.FAILED, error=str(e)),
                )

    server = AppA2AServer()
    fastapi_app = server.build_fastapi_app()

    # 兼容旧版端点
    @fastapi_app.get("/.well-known/agent.json")
    async def _legacy_agent_card():
        return card.model_dump()

    return fastapi_app


# ── Agent 动态发现 ──────────────────────────────────

class AgentDiscovery:
    """Agent 动态发现：启动时从各 Agent 的 /.well-known/agent.json 拉取能力卡片。"""

    def __init__(self, agent_urls: dict[str, str]):
        self._urls = agent_urls
        self._cards: dict[str, dict] = {}
        self._available = True

    async def discover(self) -> dict[str, dict]:
        """从配置的 URL 列表获取所有 Agent Card。"""
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            for name, url in self._urls.items():
                try:
                    resp = await client.get(f"{url}/.well-known/agent.json")
                    resp.raise_for_status()
                    self._cards[name] = resp.json()
                except Exception as e:
                    self._cards[name] = {"name": name, "url": url, "error": str(e)}
        return self._cards

    async def discover_sync(self) -> dict[str, dict]:
        """同步版 discover（启动时在 async context 调用）。"""
        return await self.discover()

    def get_agents(self) -> dict[str, dict]:
        return self._cards

    def get_agent_names(self) -> list[str]:
        return list(self._cards.keys())
