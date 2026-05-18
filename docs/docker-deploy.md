# Docker 部署说明

本项目应用服务可部署到 Docker。MySQL 和 Milvus 复用宿主机已有服务。

## 前置条件

- Docker Desktop 已启动
- 宿主机 MySQL (`3306`) 已启动，数据库 `product_scout` 已建表
- 宿主机 Milvus (`19530`) 已启动
- `.env` 中已配置 API_KEY 等真实值
- `.env` 中 `MYSQL_HOST=host.docker.internal`，`MILVUS_HOST=host.docker.internal`

## 首次启动

```powershell
cd D:\TRAE项目\A2A\ProductScout-A2A

# 1. 复制并编辑 .env
copy .env.example .env
# 编辑 .env 填入 API_KEY、MYSQL_PASSWORD、MYSQL_ROOT_PASSWORD

# 2. 导入数据（宿主机 MySQL 已启动）
cd backend
python data_scripts/import_olist.py
python data_scripts/import_amazon.py
python data_scripts/generate_business_data.py
python data_scripts/init_milvus.py
cd ..

# 3. 构建并启动所有容器
docker compose -f docker-compose.app.yml up -d --build
```

## 重建（代码变更后）

```powershell
cd D:\TRAE项目\A2A\ProductScout-A2A
docker compose -f docker-compose.app.yml build --no-cache
docker compose -f docker-compose.app.yml up -d
```

## 访问

| 服务 | 地址 |
|---|---|
| 前端 | http://localhost:5173 |
| API | http://localhost:8090 |
| API 文档 | http://localhost:8090/docs |
| MarketAgent | http://localhost:5101/.well-known/agent.json |
| ProfitAgent | http://localhost:5102/.well-known/agent.json |
| SupplyRiskAgent | http://localhost:5103/.well-known/agent.json |
| ReviewInsightAgent | http://localhost:5104/.well-known/agent.json |

## 容器服务 (10 个)

| 容器 | 端口 | 说明 |
|---|---|---|
| `productscout-market-mcp` | 8101 | 市场趋势 MCP 工具 |
| `productscout-profit-mcp` | 8102 | 利润测算 MCP 工具 |
| `productscout-supply-risk-mcp` | 8103 | 供应链风险 MCP 工具 |
| `productscout-review-mcp` | 8104 | 评论检索 MCP 工具 |
| `productscout-market-a2a` | 5101 | 市场分析 A2A Agent |
| `productscout-profit-a2a` | 5102 | 利润测算 A2A Agent |
| `productscout-supply-risk-a2a` | 5103 | 供应链风险 A2A Agent |
| `productscout-review-a2a` | 5104 | 评论洞察 A2A Agent |
| `productscout-api` | 8090 | FastAPI 主控服务 |
| `productscout-frontend` | 5173 | Vue 前端 (Nginx) |

## 架构说明 (v2.0)

容器内 Agent 调度流程：

```
API (8090)
  → IntentClassifier (意图识别)
  → UserIntentRecognizer (用户画像)
  → GlobalSlotManager (全局槽位补齐)
  → PlanningAgent (启发式 / LLM)
  → AgentSelector (动态选择 1-4 个 Agent)
  → AgentSlotValidator (Agent 专属槽位校验)
  → AgentDispatcher (信号量 + 超时 + 并行调度)
  → 4 个 A2A Agent (5101-5104)
      → 各调用对应 MCP Server (8101-8104)
          → MySQL + Milvus
  → Final LLM 报告生成
```

## 查看日志

```powershell
docker compose -f docker-compose.app.yml logs -f api
docker compose -f docker-compose.app.yml logs -f market-a2a
docker compose -f docker-compose.app.yml logs -f market-mcp
```

## 停止服务

```powershell
docker compose -f docker-compose.app.yml down
```

## 连接宿主机数据库

Compose 中通过 `host.docker.internal` 访问宿主机 MySQL 和 Milvus：

```yaml
MYSQL_HOST: host.docker.internal
MILVUS_HOST: host.docker.internal
```
