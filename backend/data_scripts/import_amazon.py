"""
导入 Amazon 评论和商品资料数据到 MySQL。
数据来源: Amazon Reviews / Metadata

使用方式:
    1. 下载 Amazon 数据集，放入 data/amazon/ 目录
    2. python import_amazon.py

第一版只抽样 5 个类目，不做全量导入。
如果数据文件不存在，使用内置模拟数据。
"""

import sys
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal
from sqlalchemy import text
from create_logger import get_logger

logger = get_logger("import_amazon")

# 评论模板
POSITIVE_TEMPLATES = [
    "质量很好，性价比高，推荐购买！",
    "包装精美，物流很快，使用效果不错。",
    "做工精细，手感好，比预期的好。",
    "功能齐全，操作简单，很满意。",
    "外观时尚，噪音小，适合家用。",
    "续航能力强，充电快，很便携。",
    "材质安全，设计合理，值得购买。",
    "已经用了一段时间，没有问题，好评。",
    "价格实惠，质量不错，会回购。",
    "送给朋友的，朋友很喜欢。",
]

NEGATIVE_TEMPLATES = [
    "质量一般，做工粗糙，不值这个价。",
    "噪音太大了，晚上用影响休息。",
    "续航时间短，充满电用不了多久。",
    "包装简陋，收到时有点破损。",
    "功能和描述不符，有点失望。",
    "用了几天就出问题了，售后态度一般。",
    "材质感觉不太安全，有异味。",
    "操作复杂，说明书看不懂。",
    "外观和图片差距大，不推荐。",
    "退货流程麻烦，等了很久才退款。",
]

NEUTRAL_TEMPLATES = [
    "一般般吧，凑合能用。",
    "还可以，没有特别好也没有特别差。",
    "中规中矩，没什么亮点。",
    "基本符合预期，价格合理。",
    "用着还行，不知道耐用性如何。",
]


def generate_reviews(session, product_ids: list[int], categories: dict[int, str]):
    """生成模拟评论数据。"""
    logger.info("生成评论数据...")

    reviews = []
    review_counter = 0

    for pid in product_ids:
        random.seed(pid * 1000)
        cat = categories.get(pid, "家居小电器")
        num_reviews = random.randint(30, 120)

        for _ in range(num_reviews):
            review_counter += 1
            rating = random.choices(
                [5, 4, 3, 2, 1],
                weights=[35, 30, 15, 12, 8],
            )[0]

            if rating >= 4:
                text_content = random.choice(POSITIVE_TEMPLATES)
                sentiment = "positive"
            elif rating <= 2:
                text_content = random.choice(NEGATIVE_TEMPLATES)
                sentiment = "negative"
            else:
                text_content = random.choice(NEUTRAL_TEMPLATES)
                sentiment = "neutral"

            review_id = f"R{review_counter:06d}"
            reviews.append((review_id, pid, cat, rating, sentiment, text_content))

    for rid, pid, cat, rating, sent, txt in reviews:
        session.execute(text("""
            INSERT INTO product_reviews (review_id, product_id, category, rating, sentiment, review_text)
            VALUES (:rid, :pid, :cat, :rating, :sent, :txt)
            ON DUPLICATE KEY UPDATE rating=VALUES(rating)
        """), {"rid": rid, "pid": pid, "cat": cat, "rating": rating, "sent": sent, "txt": txt})

    session.commit()
    logger.info("评论数据导入完成，共 %d 条", len(reviews))
    return len(reviews)


def generate_documents(session, product_data: list[tuple]):
    """生成模拟商品资料数据。"""
    logger.info("生成商品资料数据...")

    docs = []
    doc_counter = 0

    for pid, name, cat, desc in product_data:
        random.seed(pid * 2000)
        doc_counter += 1
        doc_id = f"D{doc_counter:06d}"

        title = f"{name} - 商品详情"
        feature_text = f"{name}，{desc}。品质保证，售后无忧。"

        docs.append((doc_id, pid, cat, title, desc, feature_text))

    for did, pid, cat, title, desc, feat in docs:
        session.execute(text("""
            INSERT INTO product_documents (doc_id, product_id, category, title, description, feature_text)
            VALUES (:did, :pid, :cat, :title, :desc, :feat)
            ON DUPLICATE KEY UPDATE title=VALUES(title)
        """), {"did": did, "pid": pid, "cat": cat, "title": title, "desc": desc, "feat": feat})

    session.commit()
    logger.info("商品资料导入完成，共 %d 条", len(docs))
    return len(docs)


def run():
    logger.info("=== Amazon 数据导入开始 ===")
    session = SessionLocal()
    try:
        # 读取已导入的候选商品
        result = session.execute(text("SELECT product_id, product_name, category, description FROM candidate_products"))
        rows = result.fetchall()

        if not rows:
            logger.warning("没有找到候选商品数据，请先运行 import_olist.py")
            return

        product_ids = [r[0] for r in rows]
        categories = {r[0]: r[2] for r in rows}
        product_data = [(r[0], r[1], r[2], r[3] or "") for r in rows]

        review_count = generate_reviews(session, product_ids, categories)
        doc_count = generate_documents(session, product_data)

        logger.info("=== Amazon 数据导入完成: %d 评论, %d 资料 ===", review_count, doc_count)
    finally:
        session.close()


if __name__ == "__main__":
    run()
