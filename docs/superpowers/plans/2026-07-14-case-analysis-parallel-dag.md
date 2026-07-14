# Case Analysis Parallel DAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将案件分析升级为可并行、可审计、严格结构化并可通过现有网页上传 `test_case.md` 跑通的 LangGraph 工作流。

**Architecture:** LangGraph 固定主图管理依赖、并行和降级，LangChain `create_agent()` 执行有界专业分析，服务端校验材料段落引用并确定性汇总报告。首版同步返回，不引入持久化、RAG、HITL 或 PDF 报告生成；PDF 仍作为输入通过 MinerU 解析。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、LangChain、LangGraph、Next.js、React、TypeScript、Tailwind CSS、pytest。

---

### Task 1: 固化设计与参考资产

- [ ] 写入已确认的设计说明和本实施计划，执行占位符检查：

```powershell
rg -n "T[B]D|T[O]DO|待[定]" docs/superpowers/specs/2026-07-14-case-analysis-parallel-dag-design.md docs/superpowers/plans/2026-07-14-case-analysis-parallel-dag.md
```

Expected: 无输出。

- [ ] 纳入 `docx/test_case.md` 与 `docx/案件分析-律师协作动作.html`，不得改写源内容。
- [ ] 暂存四个目标文件并核对范围：

```powershell
git diff --cached --name-only
```

Expected: 只有两份文档和两份 `docx/` 参考文件。

- [ ] 提交：

```powershell
git commit -m "docs: define parallel case analysis workflow"
```

### Task 2: 严格 Schema、证据段与并联图

**Files:**
- Create: `backend/app/schemas/case_analysis.py`
- Create: `backend/app/services/case_analysis_evidence.py`
- Create: `backend/app/services/case_analysis_agents.py`
- Create: `backend/app/services/case_analysis_graph.py`
- Test: `backend/tests/test_case_analysis_evidence.py`
- Test: `backend/tests/test_case_analysis_graph.py`

- [ ] 写严格模型和引用测试。测试至少声明以下期望 API：

```python
def test_case_agent_draft_forbids_extra_fields() -> None: ...
def test_resolve_source_refs_rejects_unknown_paragraph_id() -> None: ...
def test_segment_case_material_assigns_stable_paragraph_ids() -> None: ...
```

- [ ] 运行红灯：

```powershell
cd backend
uv run pytest tests/test_case_analysis_evidence.py -q
```

Expected: FAIL，原因是 `app.schemas.case_analysis` 或证据服务尚不存在。

- [ ] 实现 `StrictCaseModel`（`ConfigDict(extra="forbid")`）、九阶段公开结构、内部草稿结构、稳定段落 ID 和引用回填。模型只接收 `paragraph_ids`，服务层生成 `quote`。
- [ ] 运行证据与 schema 测试，Expected: PASS。
- [ ] 写图测试，至少覆盖首批节点真实重叠、最大 5 个争点、动态结果 reducer、基础节点失败、非关键节点 partial、runner 最大并发 4：

```powershell
uv run pytest tests/test_case_analysis_graph.py -q
```

Expected: FAIL，原因是 graph service 尚不存在。

- [ ] 实现 runner 协议和 `LangChainCaseAnalysisAgentRunner`：`create_agent()`、主/fallback、`asyncio.Semaphore`、120 秒 timeout、结构化响应校验和安全日志。
- [ ] 实现图状态及节点：

```python
prepare_input -> [intake_screening, fact_reconstruction, deadline_scan]
fact_reconstruction -> [evidence_review, legal_classification]
[intake_screening, deadline_scan, evidence_review, legal_classification] -> identify_issues
identify_issues -> Send("issue_worker", ...)
issue_worker -> Send("risk_worker", ...)
risk_worker -> Send("strategy_worker", ...)
strategy_worker -> build_report
```

- [ ] `build_report` 确定性生成九阶段响应；基础事实、法律分类或全部争点失败时抛出关键阶段异常，其他失败进入 `partial`。
- [ ] 运行：

```powershell
uv run pytest tests/test_case_analysis_evidence.py tests/test_case_analysis_graph.py tests/test_contract_review_graph.py -q
```

Expected: PASS。
- [ ] 提交：`git commit -m "backend: add parallel case analysis graph"`。

### Task 3: 独立 FastAPI 路由与输入边界

**Files:**
- Create: `backend/app/api/v1/case_analyses.py`
- Modify: `backend/app/api/v1/analysis.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_case_analysis_api.py`

- [ ] 写 API 测试：JSON、PDF、DOCX、MD、TXT、非法 UTF-8、空文件、错误类型、20 MiB 文件上限、60,000 字符上限、MinerU 失败、配置缺失、模型失败、结构化输出失败和 partial 响应。
- [ ] 运行红灯：

```powershell
cd backend
uv run pytest tests/test_case_analysis_api.py -q
```

Expected: FAIL，原因是独立路由和新依赖尚不存在。

- [ ] 创建独立 router 并从 `analysis.py` 删除旧 `/case-analyses` handler；`main.py` 同时注册案件 router 和原合同 router。
- [ ] PDF/DOCX 校验扩展名和 MIME 后交给 `DocumentParserProtocol`；MD/TXT 校验扩展名和 MIME 后读取 UTF-8/UTF-8 BOM，不调用 MinerU。
- [ ] 所有错误返回 `{ "error": { "code": "...", "message": "..." } }`；基础结构失败返回 502，配置缺失返回 503，非关键分支 partial 返回 200。
- [ ] 在 `Settings` 增加并发、争点、timeout 和正文上限配置并校验为正数。
- [ ] 运行：

```powershell
uv run pytest tests/test_case_analysis_api.py tests/test_analysis_api.py -q
uv run pytest -q
```

Expected: PASS。

### Task 4: 前端案件报告

**Files:**
- Create: `frontend/src/components/legal-analysis/case-analysis-report-result.tsx`
- Modify: `frontend/src/components/legal-analysis/legal-analysis-workspace.tsx`
- Modify: `frontend/src/lib/legal-analysis-types.ts`

- [ ] 扩展 TypeScript 类型，使 `CaseAnalysisResponse` 与后端结构逐字段一致，`RiskLevel` 增加 `unknown`。
- [ ] 修改上传白名单：案件为 `.pdf,.docx,.md,.txt`，合同仍为 `.pdf,.docx`；错误文案与当前模块一致。
- [ ] 创建专用结果组件，按稳定阶段顺序渲染总览、九阶段状态、时间线、证据缺口、法律关系、争点、风险、三套方案、期限、引用、限制和免责声明。
- [ ] 组件使用模块级常量/映射，避免 render 内重复构建大对象；不新增 `useEffect` 请求。
- [ ] 运行：

```powershell
cd frontend
pnpm.cmd lint
pnpm.cmd typecheck
pnpm.cmd build
```

Expected: 三条命令均 exit 0。
- [ ] 提交：`git commit -m "frontend: display staged case analysis report"`。

### Task 5: 真实链路、浏览器 QA 与交付

- [ ] 在终端 A 启动后端：

```powershell
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- [ ] 保持终端 A 运行，在终端 B 启动前端：

```powershell
cd D:\Project\Legal_AI_Agent\frontend
pnpm.cmd dev --hostname 127.0.0.1 --port 3000
```

- [ ] 从网页上传 `docx/test_case.md`，核对九阶段、婚约财产核心争点、有效段落引用、`needs_input` 和律师复核提示；不得出现无来源法条或精确胜诉概率。
- [ ] 使用浏览器插件检查桌面和移动视口、DOM、框架错误覆盖层、控制台和上传后的状态变化。
- [ ] 重新运行完整后端和前端验证命令，Expected: 全部 exit 0。
- [ ] 核对 Git 隔离：

```powershell
git status --short
git diff --cached --name-only
```

Expected: `frontend/next-env.d.ts`、`docs/project/` 和 MinerU 本地产物未被暂存。
- [ ] 推送：

```powershell
git push -u origin codex/case-analysis-parallel-dag
```

Expected: 远程新分支创建成功，不创建 PR。
