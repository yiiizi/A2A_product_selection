# Docker 部署说明

本项目的应用服务可以部署到 Docker，默认复用宿主机已有的 MySQL `3306` 和 Milvus `19530`。

## 前置条件

- Docker Desktop 已启动。
- 宿主机 MySQL 已启动，数据库为 `product_scout`，账号密码与 `.env` 一致。
- 宿主机或已有 Docker 中的 Milvus 已启动，并暴露 `19530`。
- `.env` 中已配置真实 LLM Key。

## 启动应用容器

```powershell
cd D:\TRAE项目\A2A\ProductScout-A2A
docker compose -f docker-compose.app.yml up -d --build
```

启动后访问：

- 前端：http://localhost:5173
- API：http://localhost:8090
- API 文档：http://localhost:8090/docs

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

## 容器服务

- `frontend`：Vue 静态页面 + Nginx，端口 `5173`
- `api`：FastAPI 主服务，端口 `8090`
- `market-a2a` / `profit-a2a` / `supply-risk-a2a` / `review-a2a`：4 个 A2A Agent
- `market-mcp` / `profit-mcp` / `supply-risk-mcp` / `review-mcp`：4 个 MCP 工具服务

## 连接宿主机数据库

Compose 中通过 `host.docker.internal` 访问宿主机 MySQL 与 Milvus：

```yaml
MYSQL_HOST: host.docker.internal
MILVUS_HOST: host.docker.internal
```

如果改为把 MySQL 或 Milvus 也放到同一个 compose 网络中，需要将这两个变量改成对应服务名。
