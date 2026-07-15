# `backend/app` 应用结构

本目录是 FastAPI 应用包。API 层只处理 HTTP 边界；Agent 编排、文档解析、PDF 和持久化均位于独立服务或仓储中。

所有法律分析和生成文书只供参考，必须由法律专业人士结合完整材料复核。

## 分层

| 目录或文件 | 职责 |
| --- | --- |
| `main.py` | 创建 FastAPI 应用并注册健康检查、案件分析和合同审查路由。 |
| `api/` | 请求解析、依赖装配、响应和统一错误转换。 |
| `schemas/` | API 契约和模型结构化输出；合同与案件模型分别位于独立业务子包。 |
| `services/` | `contract_review/` 与 `case_analysis/` 承载业务流程，根目录保留解析、存储和 PDF runtime 等共享基础设施。 |
| `integrations/llm/` | OpenAI-compatible 模型客户端。 |
| `repositories/` | MySQL 和 MongoDB 访问边界。 |
| `db/` | 分业务注册的 SQLAlchemy 模型、异步引擎和 Session Factory。 |
| `templates/` | 案件文书和合同审查报告的 LaTeX 模板。 |

## API

| 路由模块 | 接口 |
| --- | --- |
| `api/health.py` | `GET /health`、`GET /health/dependencies`。依赖接口只返回配置概况，不是实际存活探针。 |
| `api/v1/case_analyses/` | 案件分析创建、历史列表、历史详情和 PDF 下载；路由、依赖装配与请求解析相互分离。 |
| `api/v1/contract_reviews/` | 合同背景审查、完整合同审查报告、历史列表、历史详情和 PDF 下载。 |

受控错误统一使用：

```json
{
  "error": {
    "code": "error_code",
    "message": "面向用户的错误说明"
  }
}
```

## 案件分析调用链

```text
JSON 或 PDF/DOCX/MD/TXT
  -> 请求与文件边界校验
  -> MinerU 解析 PDF/DOCX；服务端读取 MD/TXT
  -> 证据切段并生成稳定 paragraph_id
  -> CaseAnalysisGraphService 九阶段 LangGraph
  -> 服务端校验引用并确定性汇总
  -> LaTeX 模板 + Tectonic 生成案件文书 PDF
  -> MySQL 保存结果快照和 PDF 元数据
  -> MinIO 保存 PDF
  -> 返回结果与稳定下载路径
```

关键阶段失败时请求失败；非关键阶段失败时可返回 `partial`。历史详情从 MySQL 快照恢复，PDF 从 MinIO 读取，不重新调用模型。

## 合同审查调用链

合同有两种入口：

- `POST /api/v1/contract-reviews`：只生成背景卡、合同大类、关联文件提示、缺失问题和初步陷阱。
- `POST /api/v1/contract-review-reports`：执行完整合同审查 DAG，并生成 PDF。

完整审查流程：

```text
JSON 或 PDF/DOCX 主合同与关联文件
  -> MinerU 解析和证据切段
  -> 背景审查
  -> 主体 / 形式 / 通用实质 / 关联文件并行审查
  -> 根据形式审查结果加载合同类型专项规则
  -> 汇总已有 finding_id，生成 complete 或 partial 报告
  -> LaTeX 模板 + Tectonic 生成 PDF
  -> MySQL / MongoDB / MinIO 持久化
  -> 返回结构化报告与下载路径
```

模型只能引用服务端提供的段落 ID；汇总节点只能归组已有 finding ID。未知引用、伪造发现或不合法结构均作为受控模型错误处理。

合同审查的当前端到端说明见 [`docs/contract-review/architecture/合同审查-Agent-端到端流程.md`](../../docs/contract-review/architecture/合同审查-Agent-端到端流程.md)。

## 存储边界

| 系统 | 当前用途 |
| --- | --- |
| MySQL | 合同任务、文档元数据、证据段、合同报告快照和案件分析快照。 |
| MongoDB | 合同 Agent/持久化事件、模型原始输出和 MinerU 批次审计。 |
| MinIO | 原始合同、关联文件、MinerU 产物、合同报告 PDF 和案件文书 PDF。 |
| Redis、Milvus、Neo4j | 配置预留，当前业务代码未调用。 |

数据库结构由 `backend/alembic/` 管理。存储失败时不得把未完整持久化的结果作为成功响应。

## 扩展规则

1. 在 `schemas/contract_review/` 或 `schemas/case_analysis/` 定义对应业务的请求、响应和结构化模型输出。
2. 在 `services/contract_review/` 或 `services/case_analysis/` 实现业务逻辑和 Agent 编排；共享基础设施不得反向依赖业务模块。
3. 在 `integrations/` 封装外部 SDK，在 `repositories/` 封装数据库访问。
4. 在对应的 `api/v1/` 业务子包添加路由、依赖注入和请求解析，统一错误 envelope 由 `api/errors.py` 提供。
5. 数据库变化同时添加 Alembic 迁移。
6. 在 `backend/tests/` 使用 fake/mock 覆盖正常、降级和失败路径。

## 运行与检查

```powershell
cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
uv run ruff check .
uv run pytest
```
