"""
主控集成测试。
输入固定选品需求，能返回 Top N 商品和最终报告。

运行: pytest tests/test_selection_service.py -v
前提: 所有服务已启动，MySQL 已有数据。
可选: 设置 MOCK_A2A=true 和 MOCK_LLM=true 可跳过 LLM 和 A2A 依赖。
"""

import pytest
import httpx

API_BASE = "http://localhost:8090"


@pytest.fixture
def client():
    with httpx.Client(timeout=300) as c:
        yield c


class TestSelectionAnalyze:
    def test_analyze_returns_results(self, client):
        resp = client.post(f"{API_BASE}/api/selection/analyze", json={
            "query": "帮我选一批适合夏季上新的家居小电器，客单价 100-300 元",
            "top_k": 5,
        })
        assert resp.status_code == 200
        data = resp.json()

        assert data["status"] == "success"
        assert "request_id" in data

        report = data["data"]
        assert "products" in report
        assert "final_report" in report
        assert len(report["products"]) > 0
        assert len(report["products"]) <= 5

    def test_product_has_required_fields(self, client):
        resp = client.post(f"{API_BASE}/api/selection/analyze", json={
            "query": "家居小电器 100-300元",
            "top_k": 3,
        })
        data = resp.json()
        products = data["data"]["products"]

        for p in products:
            assert "product_id" in p
            assert "final_score" in p
            assert "agent_results" in p
            assert len(p["agent_results"]) == 4
            assert "score_breakdown" in p

    def test_report_non_empty(self, client):
        resp = client.post(f"{API_BASE}/api/selection/analyze", json={
            "query": "推荐利润率高的厨房用品",
            "top_k": 3,
        })
        data = resp.json()
        assert data["data"]["final_report"]


class TestHealth:
    def test_health(self, client):
        resp = client.get(f"{API_BASE}/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestReports:
    def test_list_reports(self, client):
        resp = client.get(f"{API_BASE}/api/selection/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "total" in data
