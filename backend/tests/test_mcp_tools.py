"""
MCP 工具单元测试。
测试每个 MCP 工具输入固定参数后，返回字段完整、类型正确。

运行: pytest tests/test_mcp_tools.py -v
前提: MCP Server 已启动，MySQL 已有数据。
"""

import pytest
import httpx

MARKET_MCP = "http://localhost:8101"
PROFIT_MCP = "http://localhost:8102"
SUPPLY_RISK_MCP = "http://localhost:8103"
REVIEW_MCP = "http://localhost:8104"


@pytest.fixture
def client():
    with httpx.Client(timeout=30) as c:
        yield c


# ── Market MCP ───────────────────────────────────────

class TestMarketMCP:
    def test_query_market_trends(self, client):
        resp = client.post(f"{MARKET_MCP}/tools/query_market_trends", json={
            "category": "家居小电器", "season": "夏季", "keyword": "风扇"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "category" in data
        assert "avg_trend_score" in data
        assert isinstance(data["avg_trend_score"], (int, float))

    def test_query_competitor_products(self, client):
        resp = client.post(f"{MARKET_MCP}/tools/query_competitor_products", json={
            "category": "家居小电器", "price_min": 50, "price_max": 300, "limit": 5
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "competition_score" in data
        assert "competitors" in data
        assert isinstance(data["competitors"], list)

    def test_analyze_price_band(self, client):
        resp = client.post(f"{MARKET_MCP}/tools/analyze_price_band", json={
            "category": "家居小电器"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "price_bands" in data
        assert "suggested_band" in data


# ── Profit MCP ───────────────────────────────────────

class TestProfitMCP:
    def test_calculate_profit(self, client):
        resp = client.post(f"{PROFIT_MCP}/tools/calculate_profit", json={
            "product_id": 101, "target_price": 159
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "gross_margin" in data
        assert "profit_score" in data
        assert isinstance(data["gross_margin"], (int, float))

    def test_suggest_price(self, client):
        resp = client.post(f"{PROFIT_MCP}/tools/suggest_price", json={
            "product_id": 101, "min_margin": 20
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "suggested_price" in data
        assert data["suggested_price"] > 0

    def test_calculate_break_even(self, client):
        resp = client.post(f"{PROFIT_MCP}/tools/calculate_break_even", json={
            "product_id": 101, "fixed_cost": 5000
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "break_even_units" in data
        assert "profit_per_unit" in data


# ── Supply Risk MCP ──────────────────────────────────

class TestSupplyRiskMCP:
    def test_query_supplier(self, client):
        resp = client.post(f"{SUPPLY_RISK_MCP}/tools/query_supplier", json={
            "product_id": 101
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "suppliers" in data
        assert "avg_reliability" in data

    def test_suggest_initial_stock(self, client):
        resp = client.post(f"{SUPPLY_RISK_MCP}/tools/suggest_initial_stock", json={
            "product_id": 101, "expected_monthly_sales": 200
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "initial_stock_suggestion" in data
        assert data["initial_stock_suggestion"] > 0

    def test_evaluate_product_risk(self, client):
        resp = client.post(f"{SUPPLY_RISK_MCP}/tools/evaluate_product_risk", json={
            "product_id": 101, "category": "家居小电器"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "risk_level" in data
        assert data["risk_level"] in ("low", "medium", "high")
        assert "risk_score" in data
        assert "risk_items" in data


# ── Review MCP ───────────────────────────────────────

class TestReviewMCP:
    def test_search_reviews(self, client):
        resp = client.post(f"{REVIEW_MCP}/tools/search_reviews", json={
            "query": "静音 风扇", "category": "家居小电器", "top_k": 5
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "reviews" in data
        assert isinstance(data["reviews"], list)

    def test_search_product_documents(self, client):
        resp = client.post(f"{REVIEW_MCP}/tools/search_product_documents", json={
            "query": "桌面风扇", "category": "家居小电器", "top_k": 3
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data
        assert isinstance(data["documents"], list)

    def test_get_review_statistics(self, client):
        resp = client.post(f"{REVIEW_MCP}/tools/get_review_statistics", json={
            "product_id": 101
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "total_reviews" in data
        assert "avg_rating" in data
        assert "review_score" in data
