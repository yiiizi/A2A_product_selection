import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")


# ── LLM ──────────────────────────────────────────────
API_KEY: str = os.getenv("API_KEY", "")
BASE_URL: str = os.getenv("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen-plus")
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_ENABLE_THINKING: bool = os.getenv("LLM_ENABLE_THINKING", "false").lower() == "true"

# ── MySQL ────────────────────────────────────────────
MYSQL_HOST: str = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER: str = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "12345678")
MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "product_scout")

# ── Milvus ───────────────────────────────────────────
MILVUS_HOST: str = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT: int = int(os.getenv("MILVUS_PORT", "19530"))
MILVUS_COLLECTION_REVIEWS: str = os.getenv("MILVUS_COLLECTION_REVIEWS", "product_reviews")
MILVUS_COLLECTION_DOCUMENTS: str = os.getenv("MILVUS_COLLECTION_DOCUMENTS", "product_documents")

# ── A2A URLs ─────────────────────────────────────────
MARKET_A2A_URL: str = os.getenv("MARKET_A2A_URL", "http://localhost:5101")
PROFIT_A2A_URL: str = os.getenv("PROFIT_A2A_URL", "http://localhost:5102")
SUPPLY_RISK_A2A_URL: str = os.getenv("SUPPLY_RISK_A2A_URL", "http://localhost:5103")
REVIEW_A2A_URL: str = os.getenv("REVIEW_A2A_URL", "http://localhost:5104")

# ── MCP URLs ─────────────────────────────────────────
MARKET_MCP_URL: str = os.getenv("MARKET_MCP_URL", "http://localhost:8101/mcp")
PROFIT_MCP_URL: str = os.getenv("PROFIT_MCP_URL", "http://localhost:8102/mcp")
SUPPLY_RISK_MCP_URL: str = os.getenv("SUPPLY_RISK_MCP_URL", "http://localhost:8103/mcp")
REVIEW_MCP_URL: str = os.getenv("REVIEW_MCP_URL", "http://localhost:8104/mcp")

# ── Runtime ──────────────────────────────────────────
API_PORT: int = int(os.getenv("API_PORT", "8090"))
FRONTEND_PORT: int = int(os.getenv("FRONTEND_PORT", "5173"))
A2A_TIMEOUT_SECONDS: int = int(os.getenv("A2A_TIMEOUT_SECONDS", "120"))
MCP_TIMEOUT_SECONDS: int = int(os.getenv("MCP_TIMEOUT_SECONDS", "120"))

# ── Mock / Fallback ──────────────────────────────────
MOCK_LLM: bool = os.getenv("MOCK_LLM", "false").lower() == "true"
MOCK_A2A: bool = os.getenv("MOCK_A2A", "false").lower() == "true"
MOCK_MCP: bool = os.getenv("MOCK_MCP", "false").lower() == "true"
MOCK_MILVUS: bool = os.getenv("MOCK_MILVUS", "false").lower() == "true"
