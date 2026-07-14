# 分析历史与案件文书草稿设计

## 目标

为合同审查和案件分析增加可持久化的历史结果。合同审查可重新查看已生成的报告并下载原 PDF；案件分析在返回九阶段结果的同时，生成一份精简 DOCX 文书草稿，支持即时下载和历史查看。

首版按当前部署全局展示历史，不引入用户、权限、删除、搜索或复杂分页。后续接入账号体系后，再按用户或组织隔离记录。

## 架构与存储

采用现有 MySQL + MinIO 方案：MySQL 保存历史索引、状态和完整结果快照，MinIO 保存可下载的 PDF 或 DOCX 字节。历史详情直接从创建时快照恢复，不再调用模型。

合同审查沿用已有的 `review_task`、`context_snapshot` 和 `review_document` 数据，为 repository 增加倒序列表和按任务 ID 读取完整报告快照的能力，不复制旧数据。

案件分析新增独立快照表，字段包含：

- `analysis_id`：UUID 主键。
- `title`：用户标题或根据上传文件名形成的标题。
- `status`：`complete | partial`。
- `risk_level`：`unknown | low | medium | high`。
- `response_payload`：通过 `CaseAnalysisResponse` 校验后的完整 JSON 快照。
- `document_filename`、`document_content_type`、`document_size_bytes`、`document_sha256`、`document_object_key`：DOCX 元数据。
- `created_at` 和 `updated_at`：生成与更新时间。

数据库结构通过 Alembic 迁移创建。案件分析响应在 DOCX 成功生成且 MySQL/MinIO 成功保存后才返回给用户；任一保存环节失败均返回受控 `503`，避免出现“页面显示生成成功，历史却不存在”的状态。

## 公开接口

合同审查：

- `GET /api/v1/contract-review-reports`：返回最新 50 条历史摘要。
- `GET /api/v1/contract-review-reports/{task_id}`：返回原始 `ContractReviewReportResponse` 快照。
- `GET /api/v1/contract-review-reports/{task_id}/document`：继续使用现有 PDF 下载接口。

案件分析：

- `GET /api/v1/case-analyses`：返回最新 50 条历史摘要。
- `GET /api/v1/case-analyses/{analysis_id}`：返回原始 `CaseAnalysisResponse` 快照。
- `GET /api/v1/case-analyses/{analysis_id}/document`：下载已保存的 DOCX。

两类历史摘要统一包含 ID、标题、生成时间、状态和风险等级。合同报告的致命风险在前端保留合同模块原有样式。列表参数由服务端限制在 1–50，首版前端固定请求 50 条。

所有错误保持：

```json
{
  "error": {
    "code": "...",
    "message": "..."
  }
}
```

非法 UUID 返回 `422`，记录或文档不存在返回 `404`，快照无法校验返回受控 `500`，MySQL/MinIO 不可用返回 `503`。日志不输出完整案件内容或对象存储凭据。

## 案件 DOCX 文书草稿

DOCX 使用已经通过 Pydantic 校验的第 7 阶段 `strategy_options` 和第 8 阶段 `document_draft` 确定性生成，不新增模型调用。文件标题为“案件处理方案与文书草稿”，明确标记为草稿，不伪装成可直接提交法院的定稿。

文件只保留下列信息：

1. 三套方案对比：激进、稳健、保守；每套最多 3 个执行步骤、2 个前提和 2 个主要风险。
2. 文书草稿：文书类型、核心事实、核心请求或主张、待补信息和风险等级。
3. 专业律师复核提示。

不导出完整九阶段报告，不堆叠法条，不给出精确胜诉率。当材料不足时，文件明确写“待补充”或“待律师确认”，不虚构当事人身份、日期、法条或证据。

案件分析创建响应增加 `draft_document`，包含 `format=docx`、文件名、MIME、字节数、SHA-256、生成时间和稳定下载路径。

## 前端交互

每个模块顶部增加“新建 / 历史记录”切换，历史使用完整内容宽度，不使用右侧抽屉。用户切换合同审查或案件分析时，只显示当前模块的历史。

历史列表项展示标题、生成时间、状态、风险和“查看”操作。点击后请求历史详情，并复用现有的合同报告或案件分析结果组件。合同详情保留 PDF 下载；案件详情在顶部直接提供 DOCX 下载，不要求用户先展开第 8 阶段。

列表、详情和下载都具备独立的加载、空状态和受控错误提示。移动端将列表项纵向排布，标题允许换行，状态与操作不与标题挤在同一行。

## 校验与测试

后端按 TDD 覆盖：

- 合同与案件历史按时间倒序，且服务端硬限制最多 50 条。
- 历史详情通过严格 Pydantic 类型恢复原响应。
- 非法 UUID、不存在记录、损坏快照与存储异常转换为预定错误 envelope。
- DOCX 只组装第 7、8 阶段，限制步骤/前提/风险条目，并始终包含律师复核提示。
- DOCX 上传元数据、SHA-256、下载响应头和文件字节正确。
- 原合同审查和案件分析生成接口保持兼容。

前端覆盖：

- “新建 / 历史记录”切换及模块隔离。
- 加载、空列表、请求失败和历史详情展示。
- 合同 PDF 与案件 DOCX 下载入口。
- 移动端无水平溢出。

完整验证命令：

```powershell
cd backend
uv run ruff check .
uv run pytest

cd ../frontend
pnpm.cmd lint
pnpm.cmd typecheck
pnpm.cmd build
```

真实模型验收只在额度允许时执行一次，不进入自动化测试。

## 不在首版范围

- 登录、用户/组织隔离和权限校验。
- 历史搜索、筛选、删除、恢复、重新生成和可视化分页器。
- 案件文书 PDF、在线编辑、电子签名、律所盖章或直接提交法院。
- 为文书草稿增加额外 LLM 调用。
- 历史任务轮询、LangGraph checkpointer 或人工暂停恢复。

