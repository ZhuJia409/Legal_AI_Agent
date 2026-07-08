# Legal_AI_Agent

法律智能体应用，面向法律检索、法律问答、文档分析和案件材料整理。

## 当前已配置

- 后端：FastAPI、Pydantic Settings、LangChain、LangGraph、DeepAgents、数据库客户端依赖和健康检查接口。
- 前端：Next.js App Router、React、TypeScript、Tailwind CSS、shadcn/ui 配置和 AI SDK 依赖。
- 基础设施：本地 Docker Compose 配置，包含 MySQL、Milvus、Redis、MongoDB、MinIO。
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
