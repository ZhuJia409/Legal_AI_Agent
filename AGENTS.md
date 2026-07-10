# AGENTS.md

本文件定义 Legal_AI_Agent 项目的代码开发规范。所有参与本项目开发的 AI Agent 和人工开发者都应遵守本文档。

## 项目定位

本项目是法律智能体应用，面向法律检索、法律问答、合同审查、文档分析、类案分析和案件材料整理。

核心技术栈：

- 后端：FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、LangChain、LangGraph、DeepAgents。
- 前端：Next.js App Router、React、TypeScript、Vercel AI SDK、shadcn/ui、Tailwind CSS。
- 数据库与存储：MySQL、Milvus、Redis、MongoDB、MinIO、Neo4j。
- 模型：OpenAI-compatible API 网关、本地 embedding、本地 reranker。

## 目录职责

- `backend/`：后端 API、配置、业务服务、Agent 编排、RAG 流程、数据库访问代码。
- `frontend/`：前端页面、组件、交互状态、AI 聊天界面、引用来源展示。
- `infra/`：本地开发基础设施配置，例如 Docker Compose、数据库服务配置。
- `docs/`：技术选型、架构说明、设计参考、开发记录和项目文档。
- `scripts/`：开发、运维、初始化、数据处理等可复用脚本。
- `tests/`：跨模块测试、集成测试或端到端测试。
- `skills/`：当前项目专用技能、提示词模板、Agent 行为规范和评估标准。

不要把模型权重、数据库数据、上传文件、真实 API Key、Token、密码提交到仓库。

## 工作方式

开发前先阅读相关目录和已有实现，优先沿用项目现有模式。

改动应保持小而清晰：

- 不做与当前任务无关的重构。
- 不移动无关文件。
- 不删除用户已有改动。
- 不把临时调试代码、个人路径、真实密钥提交到仓库。

遇到问题时先定位根因，再修复代码。不要靠反复试错堆补丁。

## 本地启动规范

本项目允许使用 PyCharm 一键启动本地开发环境，但启动配置必须遵守：

- PyCharm Run Configuration 只调用项目脚本，不写入真实 API Key、Token、数据库密码或个人绝对路径。
- 本地密钥和模型服务配置只放在根目录 `.env`，不得提交到仓库。
- 一键启动脚本放在 `scripts/` 目录，脚本应清晰区分基础设施、后端和前端进程。
- 启动后端应使用 `uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`。
- 启动前端应使用 `pnpm.cmd dev --hostname 127.0.0.1 --port 3000`。
- 启动基础设施应使用 `docker compose -f infra/docker-compose.yml up -d`。
- 如果只开发前后端页面，可跳过 Docker 基础设施，但不得修改代码绕过真实模型调用路径。

复杂功能应先明确：

- 输入输出。
- 数据流。
- 错误处理。
- 权限边界。
- 测试方式。
- 对已有接口和数据结构的影响。

## 后端规范

Python 版本固定为 `3.12`，包管理使用 `uv`。

后端代码应遵守：

- API 层只负责请求校验、鉴权入口、响应封装和调用服务层。
- 业务逻辑放在 service 或 domain 模块中，不要堆在路由函数里。
- 配置统一通过 `backend/app/core/config.py` 和环境变量读取。
- 数据库访问应通过明确的 repository、DAO 或 service 边界封装。
- Pydantic schema 用于请求、响应和配置校验。
- 异步 I/O 优先使用 async 客户端。
- 不在代码里硬编码真实密钥、账号、密码、模型供应商私有配置。

## 案件分析与合同审查后端模块规范

案件分析与合同审查模块是当前后端优先建设的业务能力，目录、接口和命名应按企业级业务模块组织。

开发相关模块时应遵守：

- API 路径使用版本化资源命名，例如 `/api/v1/case-analyses` 和 `/api/v1/contract-reviews`。
- 路由代码放在 `backend/app/api/v1/`，只负责请求校验、错误响应转换和调用服务层。
- 请求和响应 schema 放在 `backend/app/schemas/`，使用 Pydantic v2 定义明确字段类型。
- 业务逻辑放在 `backend/app/services/`，案件分析和合同审查分别保持独立服务边界。
- 外部模型调用封装在 `backend/app/integrations/llm/`，通过 OpenAI-compatible API 调用真实模型。
- 运行时代码不使用 Mock fallback；缺少 API Key、网络失败或模型失败时返回受控错误。
- 测试中可以使用 Mock LLM client，避免单元测试依赖真实外部模型服务。
- 当前阶段不在案件分析与合同审查模块中引入 LangGraph、DeepAgents、RAG、向量检索或知识图谱流程。
- 法律分析结果必须包含专业法律人士复核提示，不得把模型输出直接包装成确定法律结论。

开发这些模块时优先参考项目 `skills/` 目录中的：

- `api-design`：用于接口路径、状态码、请求响应结构和错误格式。
- `python-patterns`：用于 Python 分层、类型标注、异常处理和可维护性。
- `python-testing`：用于 pytest 测试、Mock 外部依赖和边界场景覆盖。
- `verification-before-completion`：用于完成前验证 lint 和测试结果。

后端提交前至少运行：

```powershell
cd backend
uv run ruff check .
uv run pytest
```

## 前端规范

前端使用 Next.js App Router、React、TypeScript、Tailwind CSS 和 shadcn/ui。

前端代码应遵守：

- 页面放在 `frontend/src/app/`。
- 可复用组件放在 `frontend/src/components/`。
- 工具函数放在 `frontend/src/lib/`。
- 组件优先保持小而可组合。
- 所有 props 和接口数据应有明确 TypeScript 类型。
- AI 聊天、流式响应、工具调用状态和引用来源展示要有清晰的加载、错误和空状态。
- 不在前端暴露后端私密 API Key。

## 案件分析与合同审查前端模块规范

案件分析与合同审查前端模块应以法律业务工作台方式组织，不做营销页或纯展示页。

开发相关模块时应遵守：

- 浏览器侧只请求 Next.js `/api/v1/` 下的代理接口，不直接请求 FastAPI 地址。
- Next.js Route Handler 负责读取 `BACKEND_API_BASE_URL` 并转发到 FastAPI。
- 不使用 `NEXT_PUBLIC_` 暴露后端地址、模型服务地址、API Key、Token、数据库密码或对象存储密钥。
- 页面入口放在 `frontend/src/app/`，业务组件放在 `frontend/src/components/legal-analysis/`。
- 前端请求和响应类型放在 `frontend/src/lib/`，字段应与后端 Pydantic schema 保持一致。
- 表单提交、错误处理和加载状态应在用户事件处理器中完成，不通过无意义 `useEffect` 触发请求。
- 案件分析和合同审查必须具备未提交、提交中、成功、失败四类状态。
- 结果展示必须包含摘要、风险等级、主要发现、处理建议和法律专业复核提示。
- 桌面端和移动端布局都要避免文本溢出、按钮挤压和内容重叠。

开发这些模块时优先参考项目 `skills/` 目录中的：

- `frontend-design`：用于法律工作台视觉方向、信息密度、排版和交互语气。
- `frontend-patterns`：用于 React 组件拆分、表单状态、可访问性和响应式结构。
- `vercel-react-best-practices`：用于 Next.js 数据流、客户端边界和渲染性能。
- `verification-before-completion`：用于完成前验证 lint、typecheck 和 build 结果。

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

## AI Agent 与 RAG 规范

LangChain 负责模型、工具、检索和 RAG 抽象。

LangGraph 负责编排有状态、多步骤、可审计的 Agent 流程。

DeepAgents 用于复杂法律任务规划和子智能体协作。

Agent 开发必须遵守：

- 法律回答必须尽可能返回引用来源。
- 检索结果进入回答前应经过 reranker 重排。
- 不把模型输出直接当作事实，应保留证据链和来源。
- 高风险法律结论应提示用户需要人工法律专业人士复核。
- 工具调用要有明确白名单，不开放任意代码执行能力。
- Agent 事件、工具调用轨迹、检索上下文应便于后续审计。

默认模型配置：

- LLM：`qwen3.7-plus`
- Fallback LLM：`deepseek-v4-flash`
- Embedding：`BAAI/bge-m3`
- Reranker：`Qwen/Qwen3-Reranker-4B`

本地模型路径、API Key 和服务地址只应放在 `.env` 等本地配置中。

## 数据库与存储规范

MySQL 存关系型业务数据，例如用户、权限、案件、文档元数据、任务状态。

Milvus 存文档 chunk 向量和语义检索索引。

Redis 存缓存、限流、短期任务状态和临时会话状态。

MongoDB 存历史对话、Agent 事件、工具调用轨迹和非强结构化中间结果。

Neo4j 存法律知识图谱，例如法条、案例、主体、合同条款、证据材料、法律概念和争议焦点之间的实体关系。

MinIO 存原始上传文件、解析产物、报告、附件和对象文件。

数据库结构变更必须配套迁移脚本或初始化脚本，不要只改代码。

## 安全规范

严禁提交以下内容：

- `.env`
- API Key
- Token
- 数据库密码
- 云服务 Access Key
- 私钥证书
- 用户真实案件材料
- 可识别个人身份的敏感数据样本

如果密钥已经出现在聊天、日志或提交历史中，应视为泄露，并尽快轮换。

日志中不得打印完整密钥、完整身份证号、完整手机号、完整案件隐私内容。

## 测试规范

新增功能应根据风险补充测试。

最低要求：

- 配置、工具函数、RAG 关键步骤应有单元测试。
- API 路由应有请求/响应测试。
- Agent 流程应测试正常路径、无检索结果、模型失败、工具失败等场景。
- 数据库相关逻辑应覆盖连接失败、空结果和重复数据。

修复 bug 时，应优先添加能复现问题的测试，再修复。

## Git 规范

提交前检查：

```powershell
git status --short
```

只提交与当前任务相关的文件。

提交信息建议使用中文或英文短句，清楚说明改动目的，例如：

```text
docs: add project agent coding standards
backend: add health dependency config
infra: add local milvus compose service
```

不要提交：

- `.env`
- `node_modules/`
- `.venv/`
- Docker volume 数据
- 模型权重
- 本地 IDE 缓存
