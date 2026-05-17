# ProductScout A2A

电商智能选品 A2A 多智能体系统。

## 技术栈

- **后端**: FastAPI + Python
- **A2A**: 主控 + 4 个子 Agent (MarketAgent / ProfitAgent / SupplyRiskAgent / ReviewInsightAgent)
- **MCP**: 4 个工具服务
- **数据库**: MySQL + Milvus (向量检索)
- **前端**: Vue 3 + Vite + TypeScript + Element Plus + ECharts

## 快速启动

### 1. 环境准备

```bash
# 复制环境变量
cp .env.example .env
# 编辑 .env 填入 LLM API Key 等配置
```

### 2. 启动数据库

```bash
# 启动 MySQL 和 Milvus (推荐 docker-compose)
docker-compose up -d mysql milvus

# 建表
mysql -u root -p < backend/sql/create_tables.sql
mysql -u root -p < backend/sql/seed_basic_rules.sql
```

### 3. 导入数据

```bash
cd backend
python data_scripts/import_olist.py
python data_scripts/import_amazon.py
python data_scripts/generate_business_data.py
python data_scripts/init_milvus.py
```

### 4. 启动服务

```bash
# MCP Server (4 个终端)
python mcp_server/mcp_market_server.py
python mcp_server/mcp_profit_server.py
python mcp_server/mcp_supply_risk_server.py
python mcp_server/mcp_review_server.py

# A2A Agent Server (4 个终端)
python a2a_server/market_server.py
python a2a_server/profit_server.py
python a2a_server/supply_risk_server.py
python a2a_server/review_insight_server.py

# API Server
python api_server.py

# 前端
cd frontend
npm install
npm run dev
```

### 5. 访问

- 前端: http://localhost:5173
- API: http://localhost:8090
- API 文档: http://localhost:8090/docs

## 项目结构

```
ProductScout-A2A/
├── backend/
│   ├── api_server.py          # FastAPI 主服务
│   ├── selection_service.py   # 主控选品服务
│   ├── config.py              # 配置管理
│   ├── database.py            # 数据库连接
│   ├── schemas.py             # Pydantic 数据模型
│   ├── prompts.py             # LLM Prompt 管理
│   ├── scoring.py             # 综合评分模型
│   ├── create_logger.py       # 日志工具
│   ├── a2a_server/            # A2A 子 Agent 服务
│   ├── mcp_server/            # MCP 工具服务
│   ├── data_scripts/          # 数据导入脚本
│   ├── sql/                   # SQL 建表和种子数据
│   └── tests/                 # 测试文件
├── frontend/
│   └── src/
│       ├── api/               # API 调用层
│       ├── components/        # Vue 组件
│       ├── types/             # TypeScript 类型
│       └── styles/            # 样式
├── docs/                      # 项目文档
├── scripts/                   # 启动脚本
├── docker-compose.yml
├── .env.example
└── README.md
```

## 端口规划

| 服务 | 端口 |
|------|------|
| FastAPI API | 8090 |
| Vue Dev Server | 5173 |
| MarketAgent | 5101 |
| ProfitAgent | 5102 |
| SupplyRiskAgent | 5103 |
| ReviewInsightAgent | 5104 |
| Market MCP | 8101 |
| Profit MCP | 8102 |
| SupplyRisk MCP | 8103 |
| Review MCP | 8104 |
| MySQL | 3306 |
| Milvus | 19530 |
