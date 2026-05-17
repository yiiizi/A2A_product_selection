"""
A2A Agent 测试。
测试每个 Agent 能接收 A2A Task，并返回 AgentResult Schema。

运行: pytest tests/test_a2a_agents.py -v
前提: MCP Server + A2A Agent Server 已启动，MySQL 已有数据。
"""

import json
import pytest
import httpx

MARKET_A2A = "http://localhost:5101"
PROFIT_A2A = "http://localhost:5102"
SUPPLY_RISK_A2A = "http://localhost:5103"
REVIEW_A2A = "http://localhost:5104"

SAMPLE_INPUT = {
    "request_id": "test-001",
    "product": {
        "product_id": 101,
        "product_name": "折叠式桌面小风扇",
        "category": "家居小电器",
        "target_price": 159,
        "monthly_sales": 1200,
        "rating": 4.3,
    },
    "constraints": {
        "category": "家居小电器",
        "price_min": 100,
        "price_max": 300,
        "season": "夏季",
        "preferences": ["高利润", "低竞争"],
    },
    "context": {
        "user_query": "帮我选一批适合夏季上新的家居小电器",
    },
}


@pytest.fixture
def client():
    with httpx.Client(timeout=120) as c:
        yield c


def _send_a2a_task(client: httpx.Client, agent_url: str, input_data: dict) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "id": "test-task-001",
            "message": {
                "role": "user",
                "parts": [{"text": json.dumps(input_data, ensure_ascii=False)}],
            },
        },
        "id": 1,
    }
    resp = client.post(f"{agent_url}/tasks/send", json=payload)
    assert resp.status_code == 200
    return resp.json()


def _assert_agent_result(data: dict, expected_agent: str):
    result = data.get("result", {})
    assert result.get("status") == "completed", f"Task 状态异常: {result.get('error')}"

    artifacts = result.get("artifacts", [])
    assert len(artifacts) > 0, "缺少 artifacts"

    agent_output = json.loads(artifacts[0]["parts"][0]["text"])
    assert agent_output.get("agent") == expected_agent
    assert agent_output.get("product_id") == 101
    assert agent_output.get("status") == "success"
    assert "scores" in agent_output
    assert "summary" in agent_output
    return agent_output


class TestMarketAgent:
    def test_task(self, client):
        data = _send_a2a_task(client, MARKET_A2A, SAMPLE_INPUT)
        output = _assert_agent_result(data, "MarketAgent")
        assert "trend_score" in output["scores"]
        assert "competition_score" in output["scores"]


class TestProfitAgent:
    def test_task(self, client):
        data = _send_a2a_task(client, PROFIT_A2A, SAMPLE_INPUT)
        output = _assert_agent_result(data, "ProfitAgent")
        assert "profit_score" in output["scores"]


class TestSupplyRiskAgent:
    def test_task(self, client):
        data = _send_a2a_task(client, SUPPLY_RISK_A2A, SAMPLE_INPUT)
        output = _assert_agent_result(data, "SupplyRiskAgent")
        assert "supply_score" in output["scores"]
        assert "risk_score" in output["scores"]


class TestReviewInsightAgent:
    def test_task(self, client):
        data = _send_a2a_task(client, REVIEW_A2A, SAMPLE_INPUT)
        output = _assert_agent_result(data, "ReviewInsightAgent")
        assert "review_score" in output["scores"]
