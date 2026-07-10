# Legal_AI_Agent

法律智能体应用，面向法律检索、法律问答、文档分析和案件材料整理。

## 当前已配置

- 后端：FastAPI、Pydantic Settings、LangChain、LangGraph、DeepAgents、数据库客户端依赖和健康检查接口。
- 前端：Next.js App Router、React、TypeScript、Tailwind CSS、shadcn/ui 配置和 AI SDK 依赖。
- 基础设施：本地 Docker Compose 配置，包含 MySQL、Milvus、Redis、MongoDB、MinIO、neo4j。
- 模型配置：默认 embedding 为 `BAAI/bge-m3`，默认 reranker 为 `Qwen/Qwen3-Reranker-4B`。

## 快速开始

复制环境变量示例：

```powershell
Copy-Item .env.example .env
```

后端：

```powershell
cd backend
uv sync
uv run pytest
uv run uvicorn app.main:app --reload
```

前端：

```powershell
cd frontend
pnpm.cmd install
pnpm.cmd dev
```

基础设施配置校验：

```powershell
docker compose -f infra/docker-compose.yml config
```

真实模型密钥、数据库密码和 Docker Desktop 首次启动配置需要在本机手动完成。

## PyCharm 一键启动

项目仅保留一个 PyCharm Run Configuration：

- `Full Stack (Infra + Backend + Frontend)`：启动 Docker Compose 基础设施、FastAPI 后端和 Next.js 前端。

使用前请确认：

```powershell
cd D:\Project\Legal_AI_Agent\backend
uv sync

cd D:\Project\Legal_AI_Agent\frontend
pnpm.cmd install
```

在 PyCharm 顶部运行配置下拉框选择 `Full Stack (Infra + Backend + Frontend)`，点击 Run 即可。启动脚本会在控制台输出 Docker、后端、前端状态和访问地址，本地日志写入 `logs/dev/`。

启动后访问：

- 前端：http://127.0.0.1:3000
- 后端文档：http://127.0.0.1:8000/docs
