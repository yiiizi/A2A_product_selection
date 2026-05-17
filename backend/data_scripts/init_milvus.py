"""
初始化 Milvus 向量数据库。
创建 product_reviews 和 product_documents collection，并导入向量数据。

使用方式:
    python init_milvus.py

需要 Milvus 服务已启动。如果 Milvus 不可用，使用 MOCK_MILVUS=true 跳过。
"""

import sys
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    MILVUS_HOST, MILVUS_PORT,
    MILVUS_COLLECTION_REVIEWS, MILVUS_COLLECTION_DOCUMENTS,
    MOCK_MILVUS,
)
from database import SessionLocal
from sqlalchemy import text
from create_logger import get_logger

logger = get_logger("init_milvus")

EMBEDDING_DIM = 768  # 默认向量维度，可根据实际 embedding 模型调整


def get_milvus_client():
    """获取 Milvus 客户端。"""
    from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, utility

    connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)
    return connections, Collection, FieldSchema, CollectionSchema, DataType, utility


def create_reviews_collection(milvus_modules):
    """创建 product_reviews collection。"""
    connections, Collection, FieldSchema, CollectionSchema, DataType, utility = milvus_modules

    if utility.has_collection(MILVUS_COLLECTION_REVIEWS):
        logger.info("Collection %s 已存在，跳过创建", MILVUS_COLLECTION_REVIEWS)
        return Collection(MILVUS_COLLECTION_REVIEWS)

    fields = [
        FieldSchema(name="review_id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
        FieldSchema(name="product_id", dtype=DataType.INT64),
        FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="rating", dtype=DataType.FLOAT),
        FieldSchema(name="sentiment", dtype=DataType.VARCHAR, max_length=20),
        FieldSchema(name="review_text", dtype=DataType.VARCHAR, max_length=2048),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
    ]

    schema = CollectionSchema(fields, description="Product reviews with embeddings")
    collection = Collection(MILVUS_COLLECTION_REVIEWS, schema)

    # 创建索引
    index_params = {
        "metric_type": "L2",
        "index_type": "IVF_FLAT",
        "params": {"nlist": 128},
    }
    collection.create_index("embedding", index_params)
    logger.info("Collection %s 创建完成", MILVUS_COLLECTION_REVIEWS)
    return collection


def create_documents_collection(milvus_modules):
    """创建 product_documents collection。"""
    connections, Collection, FieldSchema, CollectionSchema, DataType, utility = milvus_modules

    if utility.has_collection(MILVUS_COLLECTION_DOCUMENTS):
        logger.info("Collection %s 已存在，跳过创建", MILVUS_COLLECTION_DOCUMENTS)
        return Collection(MILVUS_COLLECTION_DOCUMENTS)

    fields = [
        FieldSchema(name="doc_id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
        FieldSchema(name="product_id", dtype=DataType.INT64),
        FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="description", dtype=DataType.VARCHAR, max_length=2048),
        FieldSchema(name="feature_text", dtype=DataType.VARCHAR, max_length=2048),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
    ]

    schema = CollectionSchema(fields, description="Product documents with embeddings")
    collection = Collection(MILVUS_COLLECTION_DOCUMENTS, schema)

    index_params = {
        "metric_type": "L2",
        "index_type": "IVF_FLAT",
        "params": {"nlist": 128},
    }
    collection.create_index("embedding", index_params)
    logger.info("Collection %s 创建完成", MILVUS_COLLECTION_DOCUMENTS)
    return collection


def generate_mock_embedding(text_content: str) -> list[float]:
    """生成模拟向量（基于文本哈希的伪随机向量）。"""
    random.seed(hash(text_content) % (2**31))
    vec = [random.gauss(0, 1) for _ in range(EMBEDDING_DIM)]
    # 归一化
    norm = sum(x**2 for x in vec) ** 0.5
    return [x / norm for x in vec]


def import_reviews_to_milvus(collection, session):
    """从 MySQL 读取评论数据并导入 Milvus。"""
    logger.info("导入评论向量到 Milvus...")

    result = session.execute(text(
        "SELECT review_id, product_id, category, rating, sentiment, review_text FROM product_reviews"
    ))
    rows = result.fetchall()

    if not rows:
        logger.warning("没有评论数据，请先运行 import_amazon.py")
        return 0

    batch_size = 500
    total = 0

    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        ids = [r[0] for r in batch]
        product_ids = [r[1] for r in batch]
        categories = [r[2] or "" for r in batch]
        ratings = [float(r[3]) for r in batch]
        sentiments = [r[4] or "neutral" for r in batch]
        texts = [r[5] or "" for r in batch]
        embeddings = [generate_mock_embedding(t) for t in texts]

        collection.insert([
            ids, product_ids, categories, ratings, sentiments, texts, embeddings
        ])
        total += len(batch)

    collection.flush()
    logger.info("评论向量导入完成，共 %d 条", total)
    return total


def import_documents_to_milvus(collection, session):
    """从 MySQL 读取商品资料并导入 Milvus。"""
    logger.info("导入商品资料向量到 Milvus...")

    result = session.execute(text(
        "SELECT doc_id, product_id, category, title, description, feature_text FROM product_documents"
    ))
    rows = result.fetchall()

    if not rows:
        logger.warning("没有商品资料数据，请先运行 import_amazon.py")
        return 0

    ids = [r[0] for r in rows]
    product_ids = [r[1] for r in rows]
    categories = [r[2] or "" for r in rows]
    titles = [r[3] or "" for r in rows]
    descriptions = [r[4] or "" for r in rows]
    feature_texts = [r[5] or "" for r in rows]
    embeddings = [generate_mock_embedding(f"{t} {d} {f}") for t, d, f in zip(titles, descriptions, feature_texts)]

    collection.insert([
        ids, product_ids, categories, titles, descriptions, feature_texts, embeddings
    ])
    collection.flush()
    logger.info("商品资料向量导入完成，共 %d 条", len(rows))
    return len(rows)


def run():
    logger.info("=== Milvus 初始化开始 ===")

    if MOCK_MILVUS:
        logger.info("MOCK_MILVUS=true，跳过 Milvus 初始化")
        return

    try:
        milvus_modules = get_milvus_client()
    except Exception as e:
        logger.error("Milvus 连接失败: %s", e)
        logger.info("请确保 Milvus 已启动，或设置 MOCK_MILVUS=true")
        return

    try:
        reviews_col = create_reviews_collection(milvus_modules)
        docs_col = create_documents_collection(milvus_modules)

        session = SessionLocal()
        try:
            import_reviews_to_milvus(reviews_col, session)
            import_documents_to_milvus(docs_col, session)
        finally:
            session.close()

        logger.info("=== Milvus 初始化完成 ===")
    finally:
        milvus_modules[0].disconnect("default")


if __name__ == "__main__":
    run()
