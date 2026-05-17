"""
综合评分模型

综合评分 =
  市场趋势分 * 20%
+ 竞争优势分 * 20%
+ 利润空间分 * 25%
+ 供应链稳定分 * 15%
+ 评论机会分 * 10%
+ 风险控制分 * 10%
"""

from schemas import AgentResult

# 权重
WEIGHTS = {
    "trend_score": 0.20,
    "competition_score": 0.20,
    "profit_score": 0.25,
    "supply_score": 0.15,
    "review_score": 0.10,
    "risk_score": 0.10,
}

# 各 Agent 失败时的默认分
DEFAULT_SCORES: dict[str, dict[str, float]] = {
    "MarketAgent": {"trend_score": 60, "competition_score": 60},
    "ProfitAgent": {"profit_score": 60},
    "SupplyRiskAgent": {"supply_score": 60, "risk_score": 60},
    "ReviewInsightAgent": {"review_score": 60},
}


def _extract_scores(agent_results: dict[str, AgentResult]) -> dict[str, float]:
    """从各 Agent 结果中提取评分，失败的用默认分。"""
    merged: dict[str, float] = {}
    for agent_name, default in DEFAULT_SCORES.items():
        result = agent_results.get(agent_name)
        if result and result.status == "success":
            for k, v in result.scores.items():
                merged[k] = v
        else:
            merged.update(default)
    return merged


def competition_score_to_advantage(competition_score: float) -> float:
    """竞争越激烈分数越低，转换为竞争优势分（取反）。"""
    return 100 - competition_score


def calculate_final_score(
    agent_results: dict[str, AgentResult],
    user_intent=None,
) -> tuple[float, dict[str, float]]:
    """
    计算综合评分。

    参数:
        agent_results: 各 Agent 返回结果
        user_intent: 可选，UserIntent 对象，用于调整权重

    返回 (final_score, score_breakdown)。
    """
    scores = _extract_scores(agent_results)

    # 竞争分数转换：原始 competition_score 越高表示竞争越激烈
    # 转换为竞争优势分
    raw_competition = scores.get("competition_score", 60)
    scores["competition_score"] = competition_score_to_advantage(raw_competition)

    # 权重：默认 + 用户意图调整
    weights = dict(WEIGHTS)
    if user_intent is not None:
        try:
            from user_intent_service import UserIntentRecognizer
            weights = UserIntentRecognizer.influence_weights(user_intent, weights)
        except Exception:
            pass  # 调权失败不影响主流程

    breakdown: dict[str, float] = {}
    weighted_sum = 0.0
    total_weight = sum(weights.values())
    # 归一化
    for key, weight in weights.items():
        val = scores.get(key, 60)
        normalized_weight = weight / total_weight if total_weight > 0 else weight
        breakdown[key] = round(val, 1)
        weighted_sum += val * normalized_weight

    return round(weighted_sum, 1), breakdown


def get_recommendation(final_score: float) -> str:
    if final_score >= 80:
        return "recommend"
    elif final_score >= 60:
        return "neutral"
    else:
        return "not_recommend"
