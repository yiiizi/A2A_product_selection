"""
槽位管理器 — 全局槽位 + Agent 专属槽位校验。

职责:
  1. GlobalSlotManager: 管理全局槽位（category / season / price / preferences）
  2. AgentSlotValidator: 校验 Agent 专属槽位 + DB 自动填充 + need_more_info

设计原则:
  - 大多数 Agent 槽位可从 DB 自动填充（source=db）
  - 只有 source=user + required=True 的槽位才会触发追问
  - 缺失非关键槽位不阻塞调度，使用默认值
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from create_logger import get_logger
from database import SessionLocal
from schemas import SlotDef, SlotValidationResult

logger = get_logger("slot_manager")

# ── Agent 专属槽位定义 ───────────────────────────────

AGENT_SLOT_DEFS: dict[str, dict[str, SlotDef]] = {
    "MarketAgent": {
        "category": SlotDef(
            key="category", label="商品类目", required=True, source="user",
        ),
        "market": SlotDef(
            key="market", label="目标市场", required=False,
            default="Amazon", source="user",
        ),
        "time_range": SlotDef(
            key="time_range", label="分析时间范围", required=False,
            default="最近3个月", source="user",
        ),
    },
    "ProfitAgent": {
        "purchase_cost": SlotDef(
            key="purchase_cost", label="采购成本", required=False,
            source="db",
        ),
        "platform_fee_rate": SlotDef(
            key="platform_fee_rate", label="平台扣点率", required=False,
            source="db", default=5.0,
        ),
        "shipping_cost": SlotDef(
            key="shipping_cost", label="物流成本", required=False,
            source="db", default=0,
        ),
        "ad_cost_rate": SlotDef(
            key="ad_cost_rate", label="广告成本率", required=False,
            source="db", default=3.0,
        ),
    },
    "SupplyRiskAgent": {
        "category": SlotDef(
            key="category", label="商品类目", required=True, source="user",
        ),
        "supplier_region": SlotDef(
            key="supplier_region", label="供应商地区", required=False,
            source="db",
        ),
        "lead_time_max": SlotDef(
            key="lead_time_max", label="最大交期容忍(天)", required=False,
            default=30, source="user",
        ),
        "cert_required": SlotDef(
            key="cert_required", label="是否需要认证", required=False,
            default=False, source="derived",
        ),
    },
    "ReviewInsightAgent": {
        "search_query": SlotDef(
            key="search_query", label="检索关键词", required=False,
            source="derived",
        ),
        "min_review_count": SlotDef(
            key="min_review_count", label="最少评论数", required=False,
            default=10, source="derived",
        ),
        "rating_range_min": SlotDef(
            key="rating_range_min", label="最低评分", required=False,
            default=3.0, source="user",
        ),
    },
}


# ── GlobalSlotManager ────────────────────────────────

REQUIRED_GLOBAL_SLOTS = ["category", "season", "price_min", "price_max"]


class GlobalSlotManager:
    """全局槽位管理：提取 / 合并 / 缺失判断"""

    @staticmethod
    def merge(existing: dict, extracted: dict) -> dict:
        merged = dict(existing)
        for key, value in extracted.items():
            if value is None or value == "" or value == []:
                continue
            if key == "preferences":
                old = merged.get("preferences") or []
                merged[key] = list(dict.fromkeys([*old, *value]))
            else:
                merged[key] = value
        return merged

    @staticmethod
    def missing(slots: dict) -> list[str]:
        return [key for key in REQUIRED_GLOBAL_SLOTS if slots.get(key) in (None, "", [])]

    @staticmethod
    def is_complete(slots: dict) -> bool:
        return len(GlobalSlotManager.missing(slots)) == 0


# ── AgentSlotValidator ───────────────────────────────

@dataclass
class ValidatedAgent:
    """校验后的 Agent 结果"""
    name: str
    ready: bool
    filled_slots: dict[str, Any]
    missing_required: list[str]
    question: str = ""


class AgentSlotValidator:
    """校验 Agent 专属槽位，优先从 DB 填充，缺失必填项时生成追问"""

    @staticmethod
    def validate(
        agent_name: str,
        global_slots: dict,
        product_id: int | None = None,
    ) -> ValidatedAgent:
        """
        校验指定 Agent 的槽位:
        1. 合并全局槽位到 Agent 槽位
        2. 对 source=db 的槽位尝试数据库填充
        3. 检查 required=True + source=user 的槽位是否缺失
        """
        slot_defs = AGENT_SLOT_DEFS.get(agent_name, {})
        if not slot_defs:
            return ValidatedAgent(name=agent_name, ready=True, filled_slots=global_slots, missing_required=[])

        filled = dict(global_slots)

        # DB 填充
        if product_id is not None:
            AgentSlotValidator._fill_from_db(agent_name, product_id, filled)

        # 校验必填项
        missing: list[str] = []
        for key, sdef in slot_defs.items():
            if not sdef.required:
                continue
            val = filled.get(key)
            if val is None or val == "" or val == []:
                missing.append(key)

        # 填充默认值
        for key, sdef in slot_defs.items():
            if key not in filled or filled.get(key) is None:
                if sdef.default is not None:
                    filled[key] = sdef.default

        if missing:
            question = AgentSlotValidator._build_question(agent_name, missing)
            return ValidatedAgent(
                name=agent_name, ready=False,
                filled_slots=filled, missing_required=missing,
                question=question,
            )

        return ValidatedAgent(
            name=agent_name, ready=True,
            filled_slots=filled, missing_required=[],
        )

    @staticmethod
    def validate_all(
        agent_names: list[str],
        global_slots: dict,
        product_id: int | None = None,
    ) -> list[ValidatedAgent]:
        """批量校验多个 Agent"""
        results = []
        for name in agent_names:
            results.append(
                AgentSlotValidator.validate(name, global_slots, product_id)
            )
        return results

    @staticmethod
    def _fill_from_db(agent_name: str, product_id: int, slots: dict):
        """从数据库自动填充 Agent 专属槽位"""
        session = SessionLocal()
        try:
            if agent_name == "ProfitAgent":
                row = session.execute(text("""
                    SELECT purchase_cost, platform_fee_rate, shipping_cost, ad_cost_rate, other_cost
                    FROM product_costs WHERE product_id = :pid
                """), {"pid": product_id}).fetchone()
                if row:
                    if row[0] is not None:
                        slots.setdefault("purchase_cost", float(row[0]))
                    if row[1] is not None:
                        slots.setdefault("platform_fee_rate", float(row[1]))
                    if row[2] is not None:
                        slots.setdefault("shipping_cost", float(row[2]))
                    if row[3] is not None:
                        slots.setdefault("ad_cost_rate", float(row[3]))
                    logger.debug("ProfitAgent 槽位 DB 填充: product_id=%d", product_id)

            elif agent_name == "SupplyRiskAgent":
                row = session.execute(text("""
                    SELECT location, lead_time_days
                    FROM suppliers WHERE product_id = :pid LIMIT 1
                """), {"pid": product_id}).fetchone()
                if row:
                    if row[0]:
                        slots.setdefault("supplier_region", row[0])
                    if row[1] is not None:
                        slots.setdefault("lead_time_days", int(row[1]))
                    logger.debug("SupplyRiskAgent 槽位 DB 填充: product_id=%d", product_id)

                # cert_required: 从 risk_rules 判断
                cat = slots.get("category", "")
                risk_row = session.execute(text("""
                    SELECT COUNT(*) FROM risk_rules
                    WHERE category = :cat AND rule_type = 'compliance' AND risk_level = 'high'
                """), {"cat": cat}).fetchone()
                if risk_row and risk_row[0] > 0:
                    slots.setdefault("cert_required", True)

            elif agent_name == "ReviewInsightAgent":
                # 从产品名和类目构建搜索关键词
                product_name = slots.get("product_name", "")
                category = slots.get("category", "")
                if product_name or category:
                    slots.setdefault("search_query", f"{product_name} {category}".strip())

                # 查评论数量
                count_row = session.execute(text("""
                    SELECT COUNT(*) FROM product_reviews WHERE product_id = :pid
                """), {"pid": product_id}).fetchone()
                if count_row:
                    slots.setdefault("min_review_count", max(10, count_row[0]))

        except Exception as e:
            logger.warning("%s DB 槽位填充失败: %s", agent_name, e)
        finally:
            session.close()

    @staticmethod
    def _build_question(agent_name: str, missing: list[str]) -> str:
        slot_defs = AGENT_SLOT_DEFS.get(agent_name, {})
        labels = [slot_defs.get(k, SlotDef(key=k, label=k)).label for k in missing]

        agent_labels = {
            "MarketAgent": "市场分析",
            "ProfitAgent": "利润测算",
            "SupplyRiskAgent": "供应链风险",
            "ReviewInsightAgent": "评论洞察",
        }
        agent_label = agent_labels.get(agent_name, agent_name)
        labels_str = "、".join(labels)
        return f"要进行{agent_label}，还需要补充以下信息：{labels_str}。请提供相关数据。"
