"""
MCP Review Server (端口 8104) — fastmcp 版
提供评论检索 (Milvus)、商品资料检索、评论统计工具。
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import FastMCP
from sqlalchemy import text
from database import SessionLocal
from config import (
    MILVUS_HOST, MILVUS_PORT,
    MILVUS_COLLECTION_REVIEWS, MILVUS_COLLECTION_DOCUMENTS,
    MOCK_MILVUS,
)
from create_logger import get_logger

logger = get_logger("mcp_review_server")
mcp = FastMCP("Review MCP Server", version="2.0.0")


def _generate_mock_embedding(text_content: str, dim: int = 768) -> list[float]:
    random.seed(hash(text_content) % (2**31))
    vec = [random.gauss(0, 1) for _ in range(dim)]
    norm = sum(x**2 for x in vec) ** 0.5
    return [x / norm for x in vec]


def _milvus_search_reviews(query: str, category: str, top_k: int) -> list[dict]:
    if MOCK_MILVUS:
        return _fallback_search_reviews(query, category, top_k)
    try:
        from pymilvus import connections, Collection
        connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)
        collection = Collection(MILVUS_COLLECTION_REVIEWS)
        collection.load()
        query_embedding = _generate_mock_embedding(query)
        results = collection.search(
            data=[query_embedding], anns_field="embedding",
            param={"metric_type": "L2", "params": {"nprobe": 10}},
            limit=top_k,
            expr=f'category == "{category}"' if category else None,
            output_fields=["review_id", "product_id", "category", "rating", "sentiment", "review_text"],
        )
        reviews = []
        for hit in results[0]:
            entity = hit.entity
            reviews.append({
                "review_id": entity.get("review_id"), "product_id": entity.get("product_id"),
                "category": entity.get("category"), "rating": entity.get("rating"),
                "sentiment": entity.get("sentiment"), "review_text": entity.get("review_text"),
                "similarity": round(1 - hit.distance, 4),
            })
        connections.disconnect("default")
        return reviews
    except Exception as e:
        logger.warning("Milvus 检索失败，降级到 MySQL: %s", e)
        return _fallback_search_reviews(query, category, top_k)


def _fallback_search_reviews(query: str, category: str, top_k: int) -> list[dict]:
    session = SessionLocal()
    try:
        keywords = [kw for kw in query.replace(",", " ").split() if len(kw) > 1] or [query]
        params = {"lim": top_k}
        kw_conditions = []
        for i, kw in enumerate(keywords[:3]):
            kw_conditions.append("review_text LIKE :kw{i}")
            params[f"kw{i}"] = f"%{kw}%"
        conditions = [f"({' OR '.join(kw_conditions)})"]
        if category:
            conditions.append("category = :cat")
            params["cat"] = category
        where = " AND ".join(conditions)
        result = session.execute(text(
            f"SELECT review_id, product_id, category, rating, sentiment, review_text FROM product_reviews WHERE {where} ORDER BY rating DESC LIMIT :lim"
        ), params)
        return [{"review_id": r[0], "product_id": r[1], "category": r[2], "rating": float(r[3]), "sentiment": r[4], "review_text": r[5], "similarity": 0.0, "fallback": True} for r in result.fetchall()]
    finally:
        session.close()


def _milvus_search_documents(query: str, category: str, top_k: int) -> list[dict]:
    if MOCK_MILVUS:
        return _fallback_search_documents(query, category, top_k)
    try:
        from pymilvus import connections, Collection
        connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)
        collection = Collection(MILVUS_COLLECTION_DOCUMENTS)
        collection.load()
        query_embedding = _generate_mock_embedding(query)
        results = collection.search(
            data=[query_embedding], anns_field="embedding",
            param={"metric_type": "L2", "params": {"nprobe": 10}},
            limit=top_k,
            expr=f'category == "{category}"' if category else None,
            output_fields=["doc_id", "product_id", "category", "title", "description", "feature_text"],
        )
        docs = []
        for hit in results[0]:
            entity = hit.entity
            docs.append({
                "doc_id": entity.get("doc_id"), "product_id": entity.get("product_id"),
                "category": entity.get("category"), "title": entity.get("title"),
                "description": entity.get("description"), "feature_text": entity.get("feature_text"),
                "similarity": round(1 - hit.distance, 4),
            })
        connections.disconnect("default")
        return docs
    except Exception as e:
        logger.warning("Milvus 文档检索失败，降级到 MySQL: %s", e)
        return _fallback_search_documents(query, category, top_k)


def _fallback_search_documents(query: str, category: str, top_k: int) -> list[dict]:
    session = SessionLocal()
    try:
        params = {"lim": top_k, "q": f"%{query}%"}
        conditions = ["(title LIKE :q OR description LIKE :q OR feature_text LIKE :q)"]
        if category:
            conditions.append("category = :cat")
            params["cat"] = category
        where = " AND ".join(conditions)
        result = session.execute(text(
            f"SELECT doc_id, product_id, category, title, description, feature_text FROM product_documents WHERE {where} LIMIT :lim"
        ), params)
        return [{"doc_id": r[0], "product_id": r[1], "category": r[2], "title": r[3], "description": r[4], "feature_text": r[5], "similarity": 0.0, "fallback": True} for r in result.fetchall()]
    finally:
        session.close()


@mcp.tool()
def search_reviews(query: str, category: str = "", top_k: int = 10) -> dict:
    """检索商品评论（Milvus 向量检索，自动降级 MySQL 关键词检索）。

    参数:
        query: 搜索词（如"充电速度快"）
        category: 商品类目（可选）
        top_k: 返回数量
    """
    reviews = _milvus_search_reviews(query, category, top_k)
    return {"query": query, "category": category, "result_count": len(reviews), "reviews": reviews}


@mcp.tool()
def search_product_documents(query: str, category: str = "", top_k: int = 5) -> dict:
    """检索商品资料文档（Milvus 向量检索，自动降级 MySQL）。

    参数:
        query: 搜索词
        category: 商品类目（可选）
        top_k: 返回数量
    """
    docs = _milvus_search_documents(query, category, top_k)
    return {"query": query, "category": category, "result_count": len(docs), "documents": docs}


@mcp.tool()
def get_review_statistics(product_id: int) -> dict:
    """获取商品的评论统计（总数、平均分、好评/差评/中性比例）。

    参数:
        product_id: 商品ID
    """
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT COUNT(*) as total, AVG(rating) as avg_rating,
                SUM(CASE WHEN sentiment = 'positive' THEN 1 ELSE 0 END) as positive_count,
                SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) as negative_count,
                SUM(CASE WHEN sentiment = 'neutral' THEN 1 ELSE 0 END) as neutral_count
            FROM product_reviews WHERE product_id = :pid
        """), {"pid": product_id})
        row = result.fetchone()
        if not row or row[0] == 0:
            return {"product_id": product_id, "total": 0, "message": "暂无评论数据"}

        total = row[0]
        review_score = min(100, int(float(row[1]) * 20))
        return {
            "product_id": product_id, "total": total,
            "avg_rating": round(float(row[1]), 1), "review_score": review_score,
            "positive_count": row[2] or 0, "negative_count": row[3] or 0, "neutral_count": row[4] or 0,
            "positive_rate": round((row[2] or 0) / total * 100, 1),
        }
    finally:
        session.close()


if __name__ == "__main__":
    logger.info("Starting MCP Review Server (fastmcp) on port 8104")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8104, path="/mcp")
