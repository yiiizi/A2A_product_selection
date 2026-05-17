"""
导入 Olist 商品和订单数据到 MySQL。
数据来源: Olist Brazilian E-Commerce Public Dataset

使用方式:
    1. 下载 Olist 数据集，将 CSV 文件放入 data/olist/ 目录
    2. python import_olist.py

第一版只抽样 5 个类目，不做全量导入。
如果数据文件不存在，使用内置模拟数据。
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import engine, SessionLocal
from sqlalchemy import text
from create_logger import get_logger

logger = get_logger("import_olist")

# 推荐类目映射 (Olist葡语 -> 中文)
CATEGORY_MAP = {
    "bed_bath_table": "家居小电器",
    "kitchen_dining_laundry_garden_furniture": "厨房用品",
    "furniture_decor": "家居小电器",
    "health_beauty": "美妆个护",
    "sports_leisure": "运动户外",
    "computers_accessories": "家居小电器",
    "housewares": "厨房用品",
    "pet_shop": "宠物用品",
}

# 内置模拟数据 (当 Olist CSV 不存在时使用)
MOCK_PRODUCTS = [
    # 家居小电器
    (101, "折叠式桌面小风扇", "家居小电器", 159.00, 1200, 4.3, "USB充电 三挡风力 静音设计"),
    (102, "智能LED台灯", "家居小电器", 249.00, 800, 4.5, "护眼调光 触控开关 色温可调"),
    (103, "迷你加湿器", "家居小电器", 89.00, 2500, 4.1, "USB供电 超静音 300ml大容量"),
    (104, "桌面吸尘器", "家居小电器", 129.00, 600, 4.2, "无线充电 强力吸尘 小巧便携"),
    (105, "智能温控杯垫", "家居小电器", 199.00, 450, 4.4, "恒温55度 陶瓷面板 自动断电"),
    (106, "便携挂脖风扇", "家居小电器", 79.00, 3200, 4.0, "无叶设计 三挡风速 超长续航"),
    (107, "空气净化器桌面款", "家居小电器", 299.00, 350, 4.6, "HEPA滤网 负离子 超静音"),
    (108, "电动牙刷", "家居小电器", 169.00, 1800, 4.3, "五种模式 30天续航 IPX7防水"),
    (109, "桌面暖风机", "家居小电器", 139.00, 900, 4.1, "PTC陶瓷 两挡温度 倾倒断电"),
    (110, "迷你投影仪", "家居小电器", 289.00, 200, 4.5, "1080P 自动对焦 内置音箱"),
    # 厨房用品
    (201, "多功能料理机", "厨房用品", 259.00, 700, 4.4, "6叶刀头 大容量 多档调速"),
    (202, "空气炸锅", "厨房用品", 299.00, 1500, 4.6, "4.5L 无油烹饪 触控面板"),
    (203, "电热水壶", "厨房用品", 129.00, 2000, 4.3, "304不锈钢 1.7L 自动断电"),
    (204, "便携榨汁杯", "厨房用品", 89.00, 3000, 4.1, "USB充电 300ml 食品级材质"),
    (205, "智能电饭煲", "厨房用品", 249.00, 900, 4.5, "4L 预约定时 多功能"),
    # 宠物用品
    (301, "自动喂食器", "宠物用品", 199.00, 600, 4.3, "4L容量 定时喂食 语音录制"),
    (302, "宠物饮水机", "宠物用品", 149.00, 800, 4.4, "循环过滤 1.5L 静音水泵"),
    (303, "猫抓板", "宠物用品", 49.00, 2500, 4.2, "瓦楞纸 可替换 耐磨"),
    (304, "宠物自动逗猫棒", "宠物用品", 69.00, 1200, 4.0, "USB充电 多种模式 自动旋转"),
    (305, "宠物智能摄像头", "宠物用品", 269.00, 400, 4.5, "1080P 双向语音 夜视"),
    # 美妆个护
    (401, "面部美容仪", "美妆个护", 279.00, 500, 4.4, "射频提拉 LED光疗 多模式"),
    (402, "电动洁面仪", "美妆个护", 159.00, 900, 4.3, "硅胶刷头 声波清洁 IPX7"),
    (403, "卷发棒", "美妆个护", 129.00, 1500, 4.1, "负离子 恒温 32mm"),
    (404, "便携化妆镜", "美妆个护", 89.00, 2000, 4.5, "LED灯 三倍放大 USB充电"),
    (405, "眼部按摩仪", "美妆个护", 199.00, 600, 4.2, "气压按摩 恒温热敷 蓝牙音乐"),
    # 运动户外
    (501, "瑜伽垫", "运动户外", 99.00, 2000, 4.3, "6mm TPE 防滑 双面"),
    (502, "筋膜枪", "运动户外", 259.00, 800, 4.5, "4个按摩头 多档调节 静音"),
    (503, "跳绳", "运动户外", 39.00, 5000, 4.1, "钢丝绳 计数 防滑手柄"),
    (504, "运动水壶", "运动户外", 59.00, 3000, 4.4, "Tritan材质 750ml 防漏"),
    (505, "折叠自行车灯", "运动户外", 49.00, 1800, 4.2, "USB充电 多模式 防水"),
]


def import_mock_data(session):
    """导入内置模拟数据。"""
    logger.info("使用内置模拟数据导入候选商品...")

    for pid, name, cat, price, sales, rating, desc in MOCK_PRODUCTS:
        session.execute(text("""
            INSERT INTO candidate_products (product_id, product_name, category, price, monthly_sales, rating, description)
            VALUES (:pid, :name, :cat, :price, :sales, :rating, :desc)
            ON DUPLICATE KEY UPDATE
                product_name=VALUES(product_name), price=VALUES(price),
                monthly_sales=VALUES(monthly_sales), rating=VALUES(rating),
                description=VALUES(description)
        """), {"pid": pid, "name": name, "cat": cat, "price": price,
               "sales": sales, "rating": rating, "desc": desc})

    session.commit()
    logger.info("候选商品导入完成，共 %d 条", len(MOCK_PRODUCTS))


def import_market_trends(session):
    """导入市场趋势模拟数据。"""
    logger.info("导入市场趋势数据...")

    categories = ["家居小电器", "厨房用品", "宠物用品", "美妆个护", "运动户外"]
    seasons = ["春季", "夏季", "秋季", "冬季"]

    trend_data = []
    for cat in categories:
        for season in seasons:
            import random
            random.seed(hash(f"{cat}{season}"))
            trend_score = round(random.uniform(50, 95), 1)
            search_volume = random.randint(10000, 500000)
            growth_rate = round(random.uniform(-5, 30), 2)
            trend_data.append((cat, season, trend_score, search_volume, growth_rate))

    for cat, season, score, vol, growth in trend_data:
        session.execute(text("""
            INSERT INTO market_trends (category, season, keyword, trend_score, search_volume, growth_rate)
            VALUES (:cat, :season, :kw, :score, :vol, :growth)
            ON DUPLICATE KEY UPDATE trend_score=VALUES(trend_score)
        """), {"cat": cat, "season": season, "kw": cat, "score": score, "vol": vol, "growth": growth})

    session.commit()
    logger.info("市场趋势数据导入完成，共 %d 条", len(trend_data))


def import_competitor_products(session):
    """导入竞品模拟数据。"""
    logger.info("导入竞品数据...")

    import random
    competitors = []
    for pid, name, cat, price, *_ in MOCK_PRODUCTS:
        random.seed(pid)
        for i in range(3):
            comp_price = round(price * random.uniform(0.7, 1.3), 2)
            comp_sales = int(price * random.uniform(0.5, 2.0))
            comp_rating = round(random.uniform(3.5, 5.0), 1)
            competitors.append((
                pid, f"{name}竞品{i+1}", comp_price, comp_sales, comp_rating, "unknown"
            ))

    for pid, cname, cprice, csales, crating, platform in competitors:
        session.execute(text("""
            INSERT INTO competitor_products (product_id, competitor_name, competitor_price, competitor_sales, competitor_rating, platform)
            VALUES (:pid, :name, :price, :sales, :rating, :platform)
        """), {"pid": pid, "name": cname, "price": cprice,
               "sales": csales, "rating": crating, "platform": platform})

    session.commit()
    logger.info("竞品数据导入完成，共 %d 条", len(competitors))


def run():
    logger.info("=== Olist 数据导入开始 ===")
    session = SessionLocal()
    try:
        import_mock_data(session)
        import_market_trends(session)
        import_competitor_products(session)
        logger.info("=== Olist 数据导入完成 ===")
    finally:
        session.close()


if __name__ == "__main__":
    run()
