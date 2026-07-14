# Analysis History and Case Draft Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让合同审查可查看历史报告，并让案件分析生成、下载和查看历史 DOCX 文书草稿。

**Architecture:** 合同复用现有 MySQL 快照和 MinIO PDF；案件新增 MySQL 快照表，并将第 7、8 阶段确定性渲染为 MinIO DOCX。前端在每个模块中提供“新建 / 历史记录”切换。

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy/Alembic, MinIO, python-docx, Next.js, React, TypeScript.

---

### Task 1: 历史数据与仓储

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/20260714_0002_case_analysis_history.py`
- Modify: `backend/app/repositories/contract_review.py`
- Create: `backend/app/repositories/case_analysis.py`
- Test: `backend/tests/test_contract_review_repository.py`
- Create: `backend/tests/test_case_analysis_repository.py`

- [ ] 先增加倒序列表、详情恢复和案件快照仓储失败测试并确认失败。
- [ ] 增加案件历史表与 Alembic 迁移，实现合同/案件 repository。
- [ ] 运行仓储聚焦测试并确认通过。

### Task 2: 合同历史 API

**Files:**
- Modify: `backend/app/schemas/contract_review.py`
- Modify: `backend/app/api/v1/analysis.py`
- Modify: `backend/tests/test_contract_review_report_api.py`

- [ ] 先增加 `GET /contract-review-reports` 和 `GET /contract-review-reports/{task_id}` 失败测试。
- [ ] 实现最新 50 条摘要与严格快照恢复，保持现有 PDF 下载不变。
- [ ] 运行合同 API 聚焦测试。

### Task 3: 案件 DOCX、持久化与 API

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Modify: `backend/app/schemas/case_analysis.py`
- Create: `backend/app/services/case_analysis_document.py`
- Create: `backend/app/services/case_analysis_persistence.py`
- Modify: `backend/app/api/v1/case_analyses.py`
- Create: `backend/tests/test_case_analysis_document.py`
- Modify: `backend/tests/test_case_analysis_api.py`

- [ ] 先增加 DOCX 精简内容、持久化、历史列表/详情/下载的失败测试。
- [ ] 增加 `python-docx`，将第 7、8 阶段渲染为受限长度 DOCX，回填 `draft_document`。
- [ ] 将快照与 DOCX 写入 MySQL/MinIO，实现案件历史和下载 API。
- [ ] 运行案件 API 与 DOCX 聚焦测试。

### Task 4: Next.js 代理与历史界面

**Files:**
- Modify: `frontend/src/lib/backend-proxy.ts`
- Modify: `frontend/src/lib/legal-analysis-api.ts`
- Modify: `frontend/src/lib/legal-analysis-types.ts`
- Modify: `frontend/src/app/api/v1/contract-review-reports/route.ts`
- Create: `frontend/src/app/api/v1/contract-review-reports/[taskId]/route.ts`
- Modify: `frontend/src/app/api/v1/case-analyses/route.ts`
- Create: `frontend/src/app/api/v1/case-analyses/[analysisId]/route.ts`
- Create: `frontend/src/app/api/v1/case-analyses/[analysisId]/document/route.ts`
- Create: `frontend/src/components/legal-analysis/analysis-history.tsx`
- Modify: `frontend/src/components/legal-analysis/legal-analysis-workspace.tsx`
- Modify: `frontend/src/components/legal-analysis/case-analysis-report-result.tsx`
- Test: `frontend/src/lib/*test*`

- [ ] 先增加历史类型、GET 代理和模块隔离的失败测试。
- [ ] 实现 GET/下载代理、“新建 / 历史记录”切换、列表与详情复用。
- [ ] 在新生成和历史案件结果顶部提供 DOCX 下载。
- [ ] 运行前端聚焦测试。

### Task 5: 验证与交付

- [ ] 运行 `uv run ruff check .` 和 `uv run pytest`。
- [ ] 运行 `pnpm.cmd lint`、`pnpm.cmd typecheck` 和 `pnpm.cmd build`。
- [ ] 恢复并核对用户的 `frontend/next-env.d.ts`，检查 `git diff --check` 和 `git status --short`。
- [ ] 只提交任务文件，不提交 `.superpowers/`、`docs/project/`、MinerU 产物和用户已有改动。
