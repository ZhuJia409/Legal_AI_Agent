# Contract Report Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化合同审查 PDF 封面对齐和章节文案，删除末尾免责章节，并把前端完整审查结果精简为 PDF 下载交付页。

**Architecture:** 保持后端响应 schema 与存储结构不变，只调整 LaTeX 展示上下文、模型/追踪可见名称和 React 结果组合。所有兼容性重命名先由测试锁定，再通过真实 Tectonic、Next.js build 和可见文案扫描验收。

**Tech Stack:** Python 3.12、Jinja2、Tectonic/LaTeX、FastAPI、LangGraph、React 19、Next.js 16、TypeScript、Tailwind CSS。

## Global Constraints

- PDF 封面字段名左对齐、字段值右对齐，长文件名允许换行。
- 公开报告、前端、提示词、LLM 工具和 LangSmith 追踪不得出现旧阶段标签。
- 保留历史 Alembic 文件名和用户未跟踪目录，不改数据库 schema。
- 删除 PDF 末尾独立免责章节，但保留法律专业人士复核提示。
- 前端不展示结构化报告正文，仅展示 partial 警示、PDF 下载卡、不可用状态和复核提示。
- 不修改下载 API、安全响应头、MinIO key 和响应类型。
- 新增或修改的非显然逻辑添加简洁中文注释。

---

### Task 1: PDF 封面对齐与章节精简

**Files:**
- Modify: `backend/tests/test_contract_review_pdf.py`
- Modify: `backend/app/templates/contract_review_report.tex.j2`
- Modify: `backend/app/services/contract_review_pdf.py`

**Interfaces:**
- Consumes: `build_report_context()` 现有报告展示字段。
- Produces: 八章 PDF；封面任务信息使用左/右对齐的固定宽度列。

- [ ] **Step 1: 写入失败模板测试**

```python
@pytest.mark.asyncio
async def test_template_aligns_cover_and_omits_disclaimer_section() -> None:
    compiler = CapturingCompiler()
    renderer = ContractReviewPdfRenderer(compiler=compiler)
    await renderer.render(
        _report_response(), task_id="task-layout", title="采购合同",
        source_filename="采购合同_办公IT设备采购.docx",
        generated_at=datetime(2026, 7, 13, tzinfo=UTC),
    )
    source = compiler.latex_source
    assert r">{\raggedright\arraybackslash}" in source
    assert r">{\raggedleft\arraybackslash}" in source
    assert "二、合同背景审查" in source
    assert "背景审查提示" in source
    assert "九、免责声明" not in source
    assert "本报告由人工智能基于当前材料辅助生成" not in source
    assert "法律专业人士复核" in source
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `cd backend; uv run pytest tests/test_contract_review_pdf.py -k "aligns_cover or required_sections" -v`

Expected: FAIL，旧模板仍使用普通段落列并含九章和免责正文。

- [ ] **Step 3: 修改模板与展示上下文**

封面表格改为：

```latex
\begin{tabular}{@{}>{\raggedright\arraybackslash\bfseries\color{LegalGreen}}p{3.6cm}%
                    >{\raggedleft\arraybackslash}p{9.2cm}@{}}
```

背景章节使用“二、合同背景审查”和“背景审查提示”；删除第九章；从 `build_report_context()` 删除不再消费的顶层 `disclaimer` 键，保留 `background_disclaimer`。

- [ ] **Step 4: 运行 PDF 测试并确认 GREEN**

Run: `cd backend; uv run pytest tests/test_contract_review_pdf.py -v`

Expected: 全部通过，真实 Tectonic 测试生成有效 PDF。

---

### Task 2: 清理模型、追踪和公开说明中的旧阶段标签

**Files:**
- Modify: `backend/app/services/contract_background.py`
- Modify: `backend/app/services/contract_evidence.py`
- Modify: `backend/app/services/contract_review_graph.py`
- Modify: `backend/app/schemas/contract_background.py`
- Modify: `backend/app/api/v1/analysis.py`
- Modify: `backend/app/repositories/contract_review.py`
- Modify: `backend/app/services/contract_review_persistence.py`
- Modify: `backend/tests/test_contract_background_service.py`
- Modify: `backend/tests/test_contract_background_api.py`
- Modify: `backend/tests/test_contract_review_graph.py`
- Modify: `AGENTS.md`
- Modify: `backend/app/README.md`
- Modify: tracked Markdown files reported by the visibility scan.

**Interfaces:**
- Produces: `BACKGROUND_REVIEW_PITFALL_DEFINITIONS`、`list_background_review_related_document_types()`、LangGraph 节点 `background_review`。
- Preserves: API module value `contract_background`、响应 schema 和数据库字段。

- [ ] **Step 1: 写入失败的 prompt/trace 契约测试**

```python
def test_contract_background_prompt_and_system_prompt_use_background_review_language() -> None:
    prompt = build_contract_background_prompt("采购合同", "证据")
    assert "合同背景审查" in CONTRACT_BACKGROUND_SYSTEM_PROMPT
    assert "合同背景审查" in prompt
    assert not contains_legacy_stage_label(CONTRACT_BACKGROUND_SYSTEM_PROMPT + prompt)

@pytest.mark.asyncio
async def test_graph_runs_background_review_before_parallel_modules() -> None:
    await service.analyze(
        task_id="task-order",
        title="采购合同",
        content="合同正文",
        review_perspective="neutral",
        related_documents=(),
    )
    assert events.index("background_review:end") < events.index("party_qualification:start")
```

测试 helper 使用正则 `re.compile(r"phase\s*0", re.IGNORECASE)`，仅用于断言，不写入运行时文案。

- [ ] **Step 2: 运行目标测试并确认 RED**

Run: `cd backend; uv run pytest tests/test_contract_background_service.py tests/test_contract_review_graph.py -v`

Expected: FAIL，prompt 与节点仍使用旧名称。

- [ ] **Step 3: 重命名模型和追踪可见标识**

```python
CONTRACT_BACKGROUND_SYSTEM_PROMPT = """
你是一名谨慎的中文法律合同审查助手，当前只负责合同背景审查。
你只能使用用户提供的合同证据段和本次实际上传的关联文件名。
不得编造事实，不得使用外部知识补足合同事实。
2. 判断合同大类并生成简短中文背景审查摘要。
""".strip()
```

LangSmith 使用 `run_name="contract_background_review"`、tag `background-review`、metadata `stage="background_review"`；LangGraph 节点和测试事件统一为 `background_review`。LLM 工具改为 `list_background_review_related_document_types`。

- [ ] **Step 4: 更新公开文档、注释和历史设计文档**

把业务说明统一改为“合同背景审查”；迁移文件内容中的说明文字可更新，但文件名保持不变。不得修改用户未跟踪目录。

- [ ] **Step 5: 运行后端相关测试并确认 GREEN**

Run: `cd backend; uv run pytest tests/test_contract_background_service.py tests/test_contract_background_api.py tests/test_contract_review_graph.py -v`

Expected: 全部通过。

---

### Task 3: 前端精简为 PDF 下载交付页

**Files:**
- Modify: `frontend/src/components/legal-analysis/contract-review-report-result.tsx`
- Create: `frontend/src/components/legal-analysis/contract-review-report-result.contract.test-d.ts`
- Preserve: `frontend/src/components/legal-analysis/contract-review-document-card.tsx`

**Interfaces:**
- Consumes: `ContractReviewReportResponse.report_document` 和 `status`。
- Produces: 仅组合 `ContractReviewDocumentCard`、partial 警示、不可用状态和固定复核提示的结果组件。

- [ ] **Step 1: 写入失败的静态组件契约**

```ts
import type { ContractReviewReportResponse } from "@/lib/legal-analysis-types";

declare const result: ContractReviewReportResponse;
result.report_document?.download_path satisfies string;
result.status satisfies "complete" | "partial";
```

同时用源文件扫描测试断言不再包含“综合审查结论”“模块完成情况”“分级风险清单”“签署前提”和“证据与范围限制”。

- [ ] **Step 2: 运行 typecheck/源文件契约并确认 RED**

Run: `cd frontend; pnpm.cmd typecheck`

Run: `rg -n "综合审查结论|模块完成情况|分级风险清单|证据与范围限制" frontend/src/components/legal-analysis/contract-review-report-result.tsx`

Expected: typecheck 通过现有类型，但扫描仍命中详细正文，构成 RED。

- [ ] **Step 3: 实现极简结果组件**

```tsx
export function ContractReviewReportResult({ result }: Props) {
  return (
    <div className="mt-6 space-y-4">
      {result.status === "partial" ? <PartialWarning /> : null}
      {result.report_document ? (
        <ContractReviewDocumentCard
          document={result.report_document}
          isPartial={result.status === "partial"}
        />
      ) : (
        <DocumentUnavailableState />
      )}
      <LegalReviewNotice />
    </div>
  );
}
```

不可用状态文案为“PDF 报告文件暂不可用，请重新发起审查。”；复核提示为“下载后的报告仍须由法律专业人士结合完整材料复核。”

- [ ] **Step 4: 运行前端检查并确认 GREEN**

Run: `cd frontend; pnpm.cmd lint`

Run: `cd frontend; pnpm.cmd typecheck`

Expected: 均通过，源文件扫描不再命中详细正文标题。

---

### Task 4: 可见文案扫描、PDF 视觉验收与全量验证

**Files:**
- Inspect: all tracked files except the historical Alembic filename.
- Create ignored artifact: `.tools/contract-report-visual-check/` for local PDF/page images only.

**Interfaces:**
- Consumes: Tasks 1-3 的最终实现。
- Produces: 可复查的封面、目录、末页截图和全量测试证据。

- [ ] **Step 1: 扫描旧阶段标签残留**

Run a PowerShell scan over `git ls-files` for the retired stage label, excluding the single historical migration path and internal compatibility exceptions explicitly listed in the spec.

Expected: 用户、模型、追踪、前端和文档可见内容 0 命中。

- [ ] **Step 2: 生成真实 PDF 并转换页面图片**

使用测试报告 fixture 调用 `ContractReviewPdfRenderer`，输出到忽略目录；使用工作区 PDF 工具或 bundled Python PDF 库把封面、目录、末页转换为 PNG。

Expected: 封面字段左右对齐；目录显示“合同背景审查”；末页止于“八、审查限制”，没有独立免责章节。

- [ ] **Step 3: 运行完整验证**

Run: `cd backend; uv run ruff check .`

Run: `cd backend; uv run pytest`

Run: `cd frontend; pnpm.cmd lint`

Run: `cd frontend; pnpm.cmd typecheck`

Run: `cd frontend; pnpm.cmd build`

Expected: 全部退出码为 0；仅允许项目现有第三方弃用 warning。

- [ ] **Step 4: 检查工作树范围**

Run: `git diff --check`

Run: `git status --short`

Expected: 只包含本计划代码、测试和文档；用户原有 `frontend/next-env.d.ts` 与未跟踪目录保持未暂存；忽略目录不进入 Git。
