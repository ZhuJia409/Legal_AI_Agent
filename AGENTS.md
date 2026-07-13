# AGENTS.md

本文件定义 `Legal_AI_Agent` 项目的协作与代码开发规范。所有 AI Agent 和人工开发者在本仓库内工作时都应遵守。

## 项目定位

本项目是法律智能体应用，面向法律检索、法律问答、案件分析、合同审查、文档解析、类案分析和案件材料整理。

当前代码重点：

- 后端：FastAPI、Pydantic v2、LangChain、OpenAI-compatible LLM、MinerU 文档解析、SQLAlchemy/Alembic 预留。
- 前端：Next.js App Router、React、TypeScript、Tailwind CSS、lucide-react。
- 基础设施：MySQL、Redis、MongoDB、MinIO、Milvus、Neo4j，由 `infra/docker-compose.yml` 管理。
- 当前业务入口：`/api/v1/case-analyses` 和 `/api/v1/contract-reviews`。

法律输出必须包含专业法律人士复核提示，不得把模型输出包装成确定法律结论。

## 目录职责

- `backend/`：FastAPI 后端、配置、API 路由、业务服务、Pydantic schema、LLM/MinerU 集成、后端测试。
- `frontend/`：Next.js 前端页面、业务组件、类型定义、浏览器侧 API 代理与工作台交互。
- `infra/`：Docker Compose、本地数据库和对象存储服务配置。
- `docs/`：技术选型、架构说明、设计参考和项目文档。
- `scripts/`：本地开发、运维、初始化和数据处理脚本。
- `tests/`：跨模块、集成或端到端测试；后端单元测试目前主要在 `backend/tests/`。
- `skills/`：项目专用技能、提示词模板、Agent 行为规范和评估标准。

不要提交模型权重、Docker volume 数据、上传文件、真实 API Key、Token、密码、私钥、真实案件材料或可识别个人身份的敏感样本。

## 工作方式

- 开发前先阅读相关目录和现有实现，优先沿用项目模式。
- 保持改动小而清晰，不做无关重构、不移动无关文件、不删除用户已有改动。
- 编写或修改代码时必须添加简洁、清晰的中文注释，重点说明设计意图、业务规则、边界条件和非显然逻辑；不要用注释机械复述代码。
- 先定位根因再修复，不靠反复试错堆补丁。
- 运行时代码不使用 mock fallback；缺少配置、网络失败或模型失败时返回受控错误。
- 测试中可以使用 fake/mock LLM、MinerU、MinIO、队列或数据库适配器，避免依赖真实外部服务。
- 不在日志中打印完整密钥、完整手机号、完整身份证号或完整案件隐私内容。

## 本地启动

基础设施：

```powershell
docker compose -f infra/docker-compose.yml up -d
```

后端：

```powershell
cd backend
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd frontend
pnpm.cmd dev --hostname 127.0.0.1 --port 3000
```

本地密钥、模型服务地址、数据库密码等只放在根目录 `.env`，不得提交。

## 后端规范

- Python 固定为 `3.12`，包管理使用 `uv`。
- API 路由放在 `backend/app/api/`，版本化业务接口放在 `backend/app/api/v1/`。
- API 层只负责请求解析、依赖注入、错误响应转换和调用服务层。
- 业务逻辑放在 `backend/app/services/` 或清晰的业务模块中，不堆在路由函数里。
- 请求、响应和结构化模型 schema 放在 `backend/app/schemas/`。
- 外部模型调用统一通过 `backend/app/integrations/llm/` 或业务服务内的明确 runner 封装。
- 配置统一通过 `backend/app/core/config.py` 和环境变量读取。
- 文档上传解析走 MinerU 集成，相关逻辑在 `backend/app/services/mineru_parser.py`。
- 数据库访问必须通过 repository/DAO/service 边界封装；涉及结构变更时配套 Alembic 迁移或初始化脚本。
- 异步 I/O 优先使用 async 客户端；阻塞 SDK 应在边界处隔离。

后端提交前至少运行：

```powershell
cd backend
uv run ruff check .
uv run pytest
```

## 案件分析与合同审查后端规范

当前主分支提供：

- `POST /api/v1/case-analyses`：案件分析。
- `POST /api/v1/contract-reviews`：合同背景审查。

相关开发规则：

- 路径使用版本化资源命名，例如 `/api/v1/case-analyses`、`/api/v1/contract-reviews`。
- 路由只做请求/文件解析、错误转换和调用服务；核心逻辑放在 service。
- 合同背景审查当前使用 LangChain agent 和只读文本工具，不引入 RAG、向量检索、知识图谱、LangGraph 或 DeepAgents 流程。
- 合同背景审查只做背景卡、合同大类、关联文件提示、缺失问题和初步陷阱，不做完整法律风险审查。
- 模型输出必须经过 Pydantic 结构校验；结构不合法时返回受控错误。
- 对外错误格式保持 `{ "error": { "code": "...", "message": "..." } }`。
- 测试应覆盖正常路径、空内容、解析失败、模型配置缺失、模型失败、结构化输出失败。

## 前端规范

- 页面入口放在 `frontend/src/app/`。
- 可复用组件放在 `frontend/src/components/`，法律业务组件放在 `frontend/src/components/legal-analysis/`。
- API 请求、响应类型和代理工具放在 `frontend/src/lib/`。
- 浏览器侧只请求 Next.js `/api/v1/` 下的 Route Handler，不直接请求 FastAPI 地址。
- Next.js Route Handler 通过 `BACKEND_API_BASE_URL` 转发到后端；不要用 `NEXT_PUBLIC_` 暴露后端地址、API Key、Token 或数据库密码。
- 所有接口数据和组件 props 应有明确 TypeScript 类型。
- 表单提交、错误处理和加载状态在用户事件处理器中完成；不要用无意义 `useEffect` 触发请求。
- 上传入口支持 PDF/DOCX，并在前端做文件类型提示和基础校验。
- 结果展示应包含加载、错误、空状态和成功状态。
- 桌面端和移动端布局要避免文本溢出、按钮挤压和内容重叠。

前端提交前至少运行：

```powershell
cd frontend
pnpm.cmd lint
pnpm.cmd typecheck
```

涉及页面渲染或样式变更时，还应运行：

```powershell
cd frontend
pnpm.cmd build
```

## 数据库与存储规范

- MySQL：关系型业务数据，例如任务、用户、权限、案件、文档元数据。
- Redis：缓存、限流、短期任务状态、异步队列。
- MongoDB：对话历史、Agent 事件、工具调用轨迹、模型原始输出和非强结构化中间结果。
- MinIO：原始上传文件、解析产物、报告、附件和对象文件。
- Milvus：文档 chunk 向量和语义检索索引。
- Neo4j：法律知识图谱，例如法条、案例、主体、证据、法律概念和争议焦点关系。

本地 Docker 默认连接信息以 `infra/docker-compose.yml` 和 `.env` 为准；`.env` 覆盖 Docker Compose 默认值时，以 `.env` 为准。

数据库结构变更必须配套迁移脚本或初始化脚本，不要只改代码。

## AI、RAG 与 Agent 规范

- 法律回答应尽可能返回引用来源和证据链。
- 检索结果进入回答前应经过 reranker 重排。
- 不把模型输出直接当作事实；高风险法律结论必须提示人工法律专业人士复核。
- 工具调用必须有明确白名单，不开放任意代码执行能力。
- Agent 事件、工具调用轨迹、检索上下文应便于审计。

默认模型配置：

- LLM：`qwen3.7-plus`
- Fallback LLM：`deepseek-v4-flash`
- Embedding：`BAAI/bge-m3`
- Reranker：`Qwen/Qwen3-Reranker-4B`

本地模型路径、API Key 和服务地址只放在 `.env` 等本地配置中。

## 测试规范

- 新增功能应根据风险补充测试。
- 修复 bug 时，优先添加能复现问题的测试，再修复。
- API 路由应有请求/响应测试。
- 配置、工具函数、文档解析、结构化输出校验等关键逻辑应有单元测试。
- 外部依赖测试使用 mock/fake，避免单元测试调用真实模型、MinerU、对象存储或数据库。
- 不要为没有测试体系的模块临时引入沉重测试框架；若引入，应同步配置脚本和文档。

## Git 规范

提交前检查：

```powershell
git status --short
```

只提交与当前任务相关的文件。不要提交：

- `.env`
- `node_modules/`
- `.venv/`
- Docker volume 数据
- 模型权重
- 本地 IDE 缓存
- 上传文件和真实案件材料

提交信息使用中文或英文短句，清楚说明目的，例如：

```text
backend: add contract review task workflow
frontend: update legal analysis workspace states
docs: refresh agent development rules
```
