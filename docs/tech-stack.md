# Legal AI Agent 技术栈选型

本文档记录法律智能体应用第一阶段的技术栈选型。当前阶段只做技术选型和目录骨架，不安装依赖、不启动服务、不初始化数据库、不编写业务代码。

## 目标

- 构建面向法律检索、法律问答、文档分析、案件材料整理的智能体应用。
- 第一阶段以本地开发为主，技术选型保留未来生产化迁移空间。
- 大模型统一通过 OpenAI-compatible API 网关接入，便于后续切换 OpenAI、国产模型、vLLM、Ollama 或企业内部模型服务。

## AI 应用框架

### LangChain

LangChain 作为模型、工具、文档加载、检索增强生成（RAG）和 agent 基础抽象层。

在本项目中的职责：

- 封装 LLM、embedding、reranker 和工具调用。
- 组织法律文档切分、检索、重排、引用来源返回。
- 作为 FastAPI 服务层调用 AI 能力的主要适配层。

参考：https://docs.langchain.com/oss/python/langchain/overview

### LangGraph

LangGraph 作为有状态、多步骤、可审计 agent 流程编排框架。

在本项目中的职责：

- 编排法律问答、法条检索、案例检索、文书分析等多步骤流程。
- 管理 agent 状态、分支、重试、人工确认点和执行轨迹。
- 支撑后续长流程任务，例如合同审查、证据材料整理、诉讼策略草拟。

参考：https://docs.langchain.com/oss/python/langgraph/overview

### DeepAgents

DeepAgents 作为复杂任务规划和子智能体能力层。

在本项目中的职责：

- 处理需要规划、分解、上下文管理的复杂法律任务。
- 后续可按法律角色拆分子智能体，例如法条检索 agent、案例检索 agent、文书分析 agent、事实摘要 agent。
- 默认只开放经过项目封装的安全工具，不直接开放任意代码执行或真实文件写入能力。

参考：https://docs.langchain.com/oss/python/deepagents/overview

## 后端技术栈

推荐组合：

- Python：3.12
- Web 框架：FastAPI
- 数据校验：Pydantic v2
- ORM：SQLAlchemy 2
- 数据库迁移：Alembic
- ASGI Server：Uvicorn
- 包管理：uv

选型理由：

- FastAPI 适合类型化 API、自动 OpenAPI 文档、异步 I/O 和流式响应。
- Pydantic v2 与 FastAPI 生态结合紧密，适合定义请求、响应和配置模型。
- SQLAlchemy 2 与 Alembic 是 Python 关系型数据库开发的成熟组合。
- uv 适合快速、可复现的 Python 依赖管理。

参考：

- https://fastapi.tiangolo.com/
- https://docs.astral.sh/uv/

## 前端技术栈

推荐组合：

- Framework：Next.js App Router
- UI Runtime：React
- Language：TypeScript
- AI 前端 SDK：Vercel AI SDK
- AI UI 组件方向：AI Elements
- 组件系统：shadcn/ui
- CSS：Tailwind CSS
- 包管理：pnpm

选型理由：

- Next.js App Router 是当前 React 生态中适合全栈 AI 应用的主流框架。
- Vercel AI SDK 适合聊天、流式响应、工具调用状态、结构化输出和多模型适配。
- shadcn/ui 适合构建可维护、可定制的后台型产品界面。
- Tailwind CSS 与 shadcn/ui 组合成熟，便于快速构建法律工作台、会话界面和文档分析界面。

参考：

- https://nextjs.org/docs
- https://ai-sdk.dev/docs/introduction
- https://elements.ai-sdk.dev/
- https://ui.shadcn.com/docs

## 数据库与存储

### MySQL 8.4 LTS

用途：

- 用户、组织、角色、权限
- 案件、项目、文档元数据
- 业务配置、审计状态、任务索引

选型理由：

- 关系型数据结构清晰，生态成熟。
- 8.4 LTS 更适合作为长期维护版本。

参考：https://dev.mysql.com/doc/refman/8.4/en/mysql-releases.html

### Milvus

用途：

- 法律文档向量
- 法条、案例、合同条款、用户上传材料的语义索引
- RAG 检索召回

选型理由：

- 面向大规模向量检索，适合后续从本地开发扩展到生产集群。
- Python、LangChain 等生态支持成熟。

参考：https://milvus.io/docs/overview.md

### Redis

用途：

- 缓存
- 限流
- 会话状态
- 短期任务状态
- 流式响应过程中的临时状态

选型理由：

- 低延迟，适合缓存、锁、限流和短生命周期状态。

参考：https://redis.io/docs/latest/

### MongoDB

用途：

- 历史对话
- agent 运行事件
- 工具调用轨迹
- 检索上下文快照
- 非强结构化的分析中间结果

选型理由：

- 文档模型适合存储对话、事件流和不同 agent 输出的半结构化数据。

参考：https://www.mongodb.com/docs/manual/introduction/

### Neo4j

用途：

- 法律知识图谱
- 法条、案件、主体、合同条款、证据材料之间的实体关系
- 法律概念、案由、争议焦点、裁判规则之间的路径分析
- GraphRAG 中的实体扩展、关系召回、路径解释和可视化

选型理由：

- 原生图数据库，适合表达多跳关系、实体网络和路径推理。
- Cypher 查询语言成熟，便于描述法律实体之间的关系模式。
- 适合与 Milvus 形成互补：Milvus 负责语义相似召回，Neo4j 负责结构化关系召回和图路径分析。
- 本地开发采用 `neo4j:5.26-community`，优先选择 Neo4j 5 LTS 路线；生产环境可根据权限、备份、集群和图算法需求评估 Enterprise 版本。

参考：

- https://neo4j.com/docs/operations-manual/current/docker/
- https://neo4j.com/docs/cypher-manual/current/introduction/

### MinIO

用途：

- 原始上传文件
- 解析后的中间文件
- 导出的报告、文书、附件
- OCR 或文档解析产生的对象文件

选型理由：

- S3 兼容，适合本地开发和未来迁移到对象存储服务。

参考：https://min.io/docs/minio/linux/index.html

## 模型接入

统一采用 OpenAI-compatible API 网关。

建议环境变量：

- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`
- `EMBEDDING_MODEL`
- `RERANKER_MODEL`
- `NEO4J_URI`
- `NEO4J_USER`
- `NEO4J_PASSWORD`
- `NEO4J_DATABASE`

选型理由：

- 后端只依赖统一协议，减少供应商锁定。
- 便于在本地开发、私有化部署和云模型之间切换。
- 后续可接入 OpenAI、国产模型服务、vLLM、Ollama 或企业内部模型网关。

## Embedding 模型

默认模型：`BAAI/bge-m3`

用途：

- 中文法律文档向量化
- 多语言文档检索
- 长文档语义召回

选型理由：

- 适合中文、多语言和长文档检索场景。
- 与法律 RAG 的召回需求匹配度高。

参考：https://huggingface.co/BAAI/bge-m3

## Reranker 模型

默认模型：`Qwen/Qwen3-Reranker-4B`

用途：

- 对 Milvus 初筛召回结果进行重排。
- 提升复杂法律语义匹配、法条适用、案例相似性判断的准确率。
- 优先用于准确率要求高的法律问答和文档分析。

选型理由：

- 法律场景对精确相关性要求高，重排模型优先选择更强的 4B 版本。
- 支持复杂语义匹配，适合作为主 reranker。

参考：https://huggingface.co/Qwen/Qwen3-Reranker-4B

轻量备选：`Qwen/Qwen3-Reranker-0.6B`

适用场景：

- 本地开发机资源不足。
- 低延迟优先。
- GPU 显存不足以稳定运行 4B reranker。

Fallback：`BAAI/bge-reranker-v2-m3`

适用场景：

- 需要成熟稳定、部署简单的兼容方案。
- 需要在资源受限环境中保持较好的中文/多语言重排效果。

不默认选择：`jina-reranker-v2-base-multilingual`

原因：

- 模型能力和生态不错，但商用授权需要额外确认。
- 当前项目主路径优先选择授权和生产使用路径更清晰的模型。

## RAG 流程建议

第一版推荐流程：

1. 用户上传法律文档、合同、案件材料或法规文件。
2. 原始文件存入 MinIO。
3. 文档元数据存入 MySQL。
4. 文档解析文本、分段结果、agent 中间事件存入 MongoDB。
5. 从文档、法条、案例和合同条款中抽取实体与关系，写入 Neo4j 知识图谱。
6. 使用 `BAAI/bge-m3` 生成 chunk 向量。
7. 向量写入 Milvus。
8. 问答时先从 Milvus 召回候选 chunk，并可按实体从 Neo4j 扩展相关法条、案例、主体和争议焦点。
9. 使用 `Qwen/Qwen3-Reranker-4B` 对候选结果重排。
10. LangGraph 编排回答生成、引用来源整理、图谱路径解释，必要时触发 DeepAgents 复杂任务规划。
11. FastAPI 通过 SSE 或同等流式机制返回回答、工具状态、引用来源和图谱关系线索。

## 后续生产化方向

后续阶段再补充以下内容：

- Docker Compose 本地环境
- `.env.example`
- 后端依赖清单
- 前端依赖清单
- 数据库初始化脚本
- Milvus collection schema
- Neo4j 约束、索引和基础法律实体 schema
- MinIO bucket 初始化
- LangGraph 流程实现
- DeepAgents 工具注册与权限边界
- 观测、日志、评测与安全审计

## 当前配置状态

已完成本地开发配置：

- 后端 FastAPI 最小应用、健康检查接口、配置模块、测试配置和 AI/数据库依赖清单。
- 前端 Next.js App Router、React、TypeScript、Tailwind CSS、shadcn/ui 配置和 AI SDK 依赖。
- 本地 Docker Compose 配置，包含 MySQL 8.4、Redis、MongoDB、Neo4j、MinIO、etcd、Milvus standalone。
- 根目录 `.env.example`，保留真实密钥和密码为空。
- Git 提交作者配置为 `Zhujia409 <657864108@qq.com>`。

## 当前阶段不做的内容

- 不填写真实 API key、token 或生产密码。
- 不启动 GPU 推理服务。
- 不强制启动 Docker Desktop 或数据库容器。
- 不编写业务代码
