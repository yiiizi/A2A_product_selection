"""
生成经营模拟数据：供应商、成本、风险规则。
"""

import sys
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal
from sqlalchemy import text
from create_logger import get_logger

logger = get_logger("generate_business_data")

SUPPLIER_NAMES = [
    "深圳创新科技", "东莞品质电子", "义乌小商品供应商",
    "广州家居用品厂", "佛山电器制造", "中山照明科技",
    "杭州智能家居", "宁波电子科技", "温州日用品厂",
    "泉州运动器材", "厦门宠物用品", "上海美妆科技",
    "苏州厨房电器", "无锡生活电器", "常州户外装备",
]


def generate_suppliers(session, product_ids: list[int]):
    """为每个商品生成 1-2 个供应商。"""
    logger.info("生成供应商数据...")

    suppliers = []
    for pid in product_ids:
        random.seed(pid * 3000)
        num_suppliers = random.randint(1, 2)
        for i in range(num_suppliers):
            name = random.choice(SUPPLIER_NAMES)
            contact = f"supplier_{pid}_{i+1}@example.com"
            lead_time = random.randint(3, 15)
            moq = random.choice([50, 100, 200, 300, 500])
            reliability = round(random.uniform(70, 98), 1)
            location = random.choice(["深圳", "东莞", "义乌", "广州", "佛山", "杭州", "宁波"])
            suppliers.append((pid, name, contact, lead_time, moq, reliability, location))

    for pid, name, contact, lt, moq, rel, loc in suppliers:
        session.execute(text("""
            INSERT INTO suppliers (product_id, supplier_name, contact, lead_time_days, moq, reliability_score, location)
            VALUES (:pid, :name, :contact, :lt, :moq, :rel, :loc)
        """), {"pid": pid, "name": name, "contact": contact, "lt": lt, "moq": moq, "rel": rel, "loc": loc})

    session.commit()
    logger.info("供应商数据导入完成，共 %d 条", len(suppliers))


def generate_costs(session, product_data: list[tuple]):
    """为每个商品生成成本数据。"""
    logger.info("生成成本数据...")

    costs = []
    for pid, price in product_data:
        random.seed(pid * 4000)
        purchase_cost = round(price * random.uniform(0.3, 0.6), 2)
        platform_fee = round(random.uniform(3, 8), 2)
        shipping_cost = round(random.uniform(3, 15), 2)
        ad_cost = round(random.uniform(2, 8), 2)
        other_cost = round(random.uniform(0, 5), 2)
        costs.append((pid, purchase_cost, platform_fee, shipping_cost, ad_cost, other_cost))

    for pid, pc, pf, sc, ac, oc in costs:
        session.execute(text("""
            INSERT INTO product_costs (product_id, purchase_cost, platform_fee_rate, shipping_cost, ad_cost_rate, other_cost)
            VALUES (:pid, :pc, :pf, :sc, :ac, :oc)
            ON DUPLICATE KEY UPDATE purchase_cost=VALUES(purchase_cost)
        """), {"pid": pid, "pc": pc, "pf": pf, "sc": sc, "ac": ac, "oc": oc})

    session.commit()
    logger.info("成本数据导入完成，共 %d 条", len(costs))


def run():
    logger.info("=== 经营数据生成开始 ===")
    session = SessionLocal()
    try:
        result = session.execute(text("SELECT product_id, price FROM candidate_products"))
        rows = result.fetchall()

        if not rows:
            logger.warning("没有找到候选商品数据，请先运行 import_olist.py")
            return

        product_ids = [r[0] for r in rows]
        product_data = [(r[0], float(r[1])) for r in rows]

        generate_suppliers(session, product_ids)
        generate_costs(session, product_data)

        logger.info("=== 经营数据生成完成 ===")
    finally:
        session.close()


if __name__ == "__main__":
    run()
