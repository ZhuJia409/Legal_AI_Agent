# AGENTS.md

本文件定义 Legal_AI_Agent 项目的代码开发规范。所有参与本项目开发的 AI Agent 和人工开发者都应遵守本文档。

## 项目定位

本项目是法律智能体应用，面向法律检索、法律问答、合同审查、文档分析、类案分析和案件材料整理。

核心技术栈：

- 后端：FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、LangChain、LangGraph、DeepAgents。
- 前端：Next.js App Router、React、TypeScript、Vercel AI SDK、shadcn/ui、Tailwind CSS。
- 数据库与存储：MySQL、Milvus、Redis、MongoDB、MinIO。
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

- LLM：`qwen3.6-flash`
- Fallback LLM：`qwen-plus`
- Embedding：`BAAI/bge-m3`
- Reranker：`Qwen/Qwen3-Reranker-4B`

本地模型路径、API Key 和服务地址只应放在 `.env` 等本地配置中。

## 数据库与存储规范

MySQL 存关系型业务数据，例如用户、权限、案件、文档元数据、任务状态。

Milvus 存文档 chunk 向量和语义检索索引。

Redis 存缓存、限流、短期任务状态和临时会话状态。

MongoDB 存历史对话、Agent 事件、工具调用轨迹和非强结构化中间结果。

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

## 推荐参考技能

本规范参考了当前环境中可用的软件开发方法类技能：

- `brainstorming`：用于复杂功能前澄清架构、组件、数据流、错误处理和测试。
- `systematic-debugging`：用于问题定位，要求先找根因再修复。
- `test-driven-development`：用于高风险功能和 bug 修复。
- `verification-before-completion`：用于完成前运行验证命令，以结果为准。
- `requesting-code-review`：用于较大改动完成后做代码审查。

当任务复杂、影响范围大或涉及核心架构时，应优先采用这些方法。
