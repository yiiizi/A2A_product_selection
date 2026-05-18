# LangGraph 工作流说明

项目的主选品链路已迁移为 LangGraph 状态图，入口位于 `backend/langgraph_selection_workflow.py`。

## 节点结构

```text
START
  -> recognize_intent
  -> build_plan
  -> select_agents
  -> query_candidates
  -> validate_slots
  -> dispatch_agents
  -> rank_products
  -> generate_report
  -> persist_report
  -> finalize_report
END
```

条件分支：

- `build_plan` 无需调用 Agent 时进入 `skip_report`。
- `query_candidates` 未找到候选商品时进入 `no_candidates_report`。
- `validate_slots` 发现 Agent 缺少必要槽位时进入 `validation_report`。

## 兼容入口

`backend/pipeline.py` 保留原有函数名：

- `run_full_pipeline()`：用于 `/api/selection/analyze`
- `stream_full_pipeline()`：用于聊天 SSE 流式输出

这两个函数现在都委托给 LangGraph 工作流，前端和 API 路由不需要改动。

## A2A 关系

LangGraph 负责主流程编排；每个业务 Agent 仍通过 A2A 服务调用：

- `MarketAgent`
- `ProfitAgent`
- `SupplyRiskAgent`
- `ReviewInsightAgent`

各 Agent 内部继续通过 MCP 工具获取市场、利润、供应链和评论数据。
