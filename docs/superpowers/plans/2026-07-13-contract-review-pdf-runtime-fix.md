# Contract Review PDF Runtime Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Windows Uvicorn reload/multi-worker 下合同审查 PDF 无法启动 Tectonic 的问题，并为 PDF 失败与 HTTP URL 提供不泄密的安全日志。

**Architecture:** `TectonicCompiler` 保留异步协议，但把完整同步编译生命周期放入 `asyncio.to_thread`，由 `subprocess.run` 自己处理 timeout、终止和回收。PDF 异常增加只读安全诊断字段；应用根 handler 安装 URL 查询参数脱敏 Filter，公开 API 契约保持不变。

**Tech Stack:** Python 3.12、FastAPI、asyncio、subprocess、pytest、pytest-asyncio、ruff。

## Global Constraints

- 不新增数据库迁移，不改变 `/api/v1/contract-reviews` Phase 0 行为。
- `pdf_renderer_unavailable` 仍返回 503，`report_pdf_generation_error` 仍返回 500。
- Tectonic 必须继续使用 `--only-cached`，不得启用 shell 或联网下载宏包。
- 不记录合同正文、LaTeX、Tectonic stdout/stderr、URL 查询参数、密钥或 token。
- 所有新增或修改的非显然逻辑添加简洁中文注释。
- 保留用户已有 `frontend/next-env.d.ts` 与未跟踪文档目录，不纳入提交。

---

### Task 1: 用线程隔离的同步 Tectonic 边界替换 asyncio 子进程

**Files:**
- Modify: `backend/tests/test_contract_review_pdf.py:528`
- Modify: `backend/app/services/contract_review_pdf.py:1-190`

**Interfaces:**
- Consumes: `TectonicCompiler.compile(latex_source: str) -> bytes` 现有协议与配置。
- Produces: `ReportPdfGenerationError(message, *, failure_stage, cause_type=None, return_code=None)`；`PdfRendererUnavailableError` 保持其子类关系。

- [ ] **Step 1: 写入失败测试，声明同步 runner 与安全诊断契约**

```python
@pytest.mark.asyncio
async def test_tectonic_compiler_uses_threaded_subprocess_without_asyncio_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "tectonic.exe"
    executable.write_bytes(b"fake")
    captured: dict[str, object] = {}

    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("不得依赖 asyncio 子进程")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        output_dir = Path(args[args.index("--outdir") + 1])
        (output_dir / "report.pdf").write_bytes(b"%PDF-1.7\nfixture")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_if_called)
    monkeypatch.setattr(subprocess, "run", fake_run)
    compiler = TectonicCompiler(tectonic_path=executable, repository_root=tmp_path)
    content = await compiler.compile("中文正文")
    assert content.startswith(b"%PDF-")
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["stdout"] is subprocess.DEVNULL
    assert captured["kwargs"]["stderr"] is subprocess.DEVNULL

@pytest.mark.asyncio
async def test_tectonic_timeout_has_safe_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "tectonic.exe"
    executable.write_bytes(b"fake")

    def raise_timeout_with_secret_stderr(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(
            cmd="tectonic", timeout=0.01, stderr=b"contract-secret"
        )

    monkeypatch.setattr(subprocess, "run", raise_timeout_with_secret_stderr)
    compiler = TectonicCompiler(tectonic_path=executable, timeout_seconds=0.01)
    with pytest.raises(ReportPdfGenerationError) as exc_info:
        await compiler.compile("合同正文")
    assert exc_info.value.failure_stage == "compile_timeout"
    assert exc_info.value.cause_type == "TimeoutExpired"
    assert exc_info.value.return_code is None
    assert "合同秘密" not in str(exc_info.value)
```

- [ ] **Step 2: 运行目标测试并确认 RED**

Run: `cd backend; uv run pytest tests/test_contract_review_pdf.py -k "threaded_subprocess or safe_diagnostics" -v`

Expected: FAIL，因为当前实现调用 `asyncio.create_subprocess_exec`，异常没有 `failure_stage`。

- [ ] **Step 3: 实现最小异常元数据与同步 runner**

```python
class ReportPdfGenerationError(RuntimeError):
    def __init__(self, message: str, *, failure_stage: str, cause_type: str | None = None,
                 return_code: int | None = None) -> None:
        super().__init__(message)
        self.failure_stage = failure_stage
        self.cause_type = cause_type
        self.return_code = return_code

async def compile(self, latex_source: str) -> bytes:
    return await asyncio.to_thread(self._compile_sync, latex_source)

def _compile_sync(self, latex_source: str) -> bytes:
    if not self._executable_path.is_file():
        error = FileNotFoundError(self._executable_path)
        raise PdfRendererUnavailableError(
            "Tectonic PDF 渲染器不可用",
            failure_stage="renderer_unavailable",
            cause_type=type(error).__name__,
        ) from error
    with tempfile.TemporaryDirectory(prefix="contract-review-pdf-") as temp_dir:
        working_directory = Path(temp_dir)
        source_path = working_directory / "report.tex"
        output_path = working_directory / "report.pdf"
        source_path.write_text(latex_source, encoding="utf-8")
        process_environment = os.environ.copy()
        process_environment["TECTONIC_CACHE_DIR"] = str(self._cache_directory)
        command = [
            str(self._executable_path), "--only-cached", "--keep-logs", "--outdir",
            str(working_directory), "report.tex",
        ]
        try:
            completed = subprocess.run(
                command, cwd=str(working_directory), env=process_environment,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=self._timeout_seconds, check=False, shell=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ReportPdfGenerationError(
                "合同审查报告 PDF 编译超时",
                failure_stage="compile_timeout",
                cause_type=type(error).__name__,
            ) from error
        except OSError as error:
            raise PdfRendererUnavailableError(
                "Tectonic PDF 渲染器无法启动",
                failure_stage="process_start",
                cause_type=type(error).__name__,
            ) from error
        if completed.returncode != 0:
            raise ReportPdfGenerationError(
                f"Tectonic 编译失败（退出码 {completed.returncode}）",
                failure_stage="compile_exit",
                return_code=completed.returncode,
            )
        if not output_path.is_file():
            raise ReportPdfGenerationError(
                "Tectonic 未生成报告 PDF 文件", failure_stage="output_validation"
            )
        content = output_path.read_bytes()
        if not content or not content.startswith(b"%PDF-"):
            raise ReportPdfGenerationError(
                "Tectonic 输出不是有效 PDF", failure_stage="output_validation"
            )
        return content
```

为缺失文件、`OSError`、`TimeoutExpired`、非零退出、缺失/空/非法 PDF 分别设置设计文档规定的 `failure_stage`，不把异常原文或输出写入公开消息。

- [ ] **Step 4: 迁移现有启动失败、超时、退出码、取消和输出校验测试**

把依赖 `FakeTectonicProcess` 的测试改为 monkeypatch `subprocess.run`。取消测试用 `threading.Event` 阻塞 fake runner，验证取消传播后线程最终清理临时目录；不得断言事件循环能立即杀死工作线程。

- [ ] **Step 5: 运行 PDF 测试并确认 GREEN**

Run: `cd backend; uv run pytest tests/test_contract_review_pdf.py -v`

Expected: 全部通过，包括真实 Tectonic 集成测试（本机已安装时）。

---

### Task 2: 增加 URL 查询参数日志脱敏

**Files:**
- Create: `backend/app/core/logging.py`
- Create: `backend/tests/test_logging.py`
- Modify: `backend/app/main.py:1-16`

**Interfaces:**
- Produces: `redact_url_queries(value: str) -> str`、`SensitiveUrlFilter(logging.Filter)`、`configure_logging() -> None`。
- Consumes: Python 标准库 `logging` 与 `urllib.parse`；不依赖 httpx 内部类型。

- [ ] **Step 1: 写入失败测试，覆盖参数化 httpx 消息与普通日志**

```python
def test_sensitive_url_filter_removes_query_and_fragment() -> None:
    record = logging.LogRecord(
        "httpx", logging.INFO, __file__, 1,
        'HTTP Request: %s %s "%s"',
        ("PUT", "https://mineru.example/upload/file?OSSAccessKeyId=id&Signature=secret#x", "200 OK"),
        None,
    )
    assert SensitiveUrlFilter().filter(record) is True
    message = record.getMessage()
    assert message == 'HTTP Request: PUT https://mineru.example/upload/file "200 OK"'
    assert "Signature" not in message

def test_configure_logging_installs_filter_once_on_root_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = logging.getLogger()
    handler = logging.StreamHandler()
    monkeypatch.setattr(root, "handlers", [handler])
    configure_logging()
    configure_logging()
    assert sum(isinstance(item, SensitiveUrlFilter) for item in handler.filters) == 1
```

- [ ] **Step 2: 运行日志测试并确认 RED**

Run: `cd backend; uv run pytest tests/test_logging.py -v`

Expected: ERROR/FAIL，因为日志模块与 Filter 尚不存在。

- [ ] **Step 3: 实现脱敏函数、Filter 和幂等配置**

```python
_HTTP_URL_PATTERN = re.compile(r"https?://[^\s\"']+")

def redact_url_queries(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        url = match.group(0)
        parsed = urlsplit(url)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return _HTTP_URL_PATTERN.sub(replace, value)

class SensitiveUrlFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        record.msg = redact_url_queries(message)
        record.args = ()
        return True
```

`configure_logging` 先调用 `logging.basicConfig`，再对 root handlers 幂等安装 Filter；`app.main` 改为从该模块导入配置函数。

- [ ] **Step 4: 运行日志与应用启动测试并确认 GREEN**

Run: `cd backend; uv run pytest tests/test_logging.py tests/test_health.py -v`

Expected: 全部通过，重复创建 app 不产生重复 Filter。

---

### Task 3: API 写入安全 PDF 诊断字段

**Files:**
- Modify: `backend/tests/test_contract_review_report_api.py:310-340`
- Modify: `backend/app/api/v1/analysis.py:730-760`

**Interfaces:**
- Consumes: Task 1 的 `failure_stage`、`cause_type`、`return_code`。
- Produces: 安全结构化 warning；公开 JSON 和 HTTP 状态保持原样。

- [ ] **Step 1: 写入失败测试，验证日志字段且不泄露异常消息**

```python
def test_contract_review_report_pdf_error_logs_safe_diagnostics(client, caplog):
    error = ReportPdfGenerationError(
        "不得记录的合同秘密", failure_stage="compile_exit",
        cause_type="CalledProcessError", return_code=1,
    )
    app.dependency_overrides[get_contract_review_graph_service] = (
        lambda: StubContractReviewGraphService()
    )
    app.dependency_overrides[get_contract_review_persistence_service] = (
        lambda: StubReportPersistenceService()
    )
    app.dependency_overrides[get_contract_review_pdf_renderer] = (
        lambda: StubPdfRenderer(error=error)
    )
    response = client.post("/api/v1/contract-review-reports", json={"content": "合同正文"})
    assert response.status_code == 500
    assert "failure_stage=compile_exit" in caplog.text
    assert "return_code=1" in caplog.text
    assert "不得记录的合同秘密" not in caplog.text
```

- [ ] **Step 2: 运行目标 API 测试并确认 RED**

Run: `cd backend; uv run pytest tests/test_contract_review_report_api.py -k "pdf_error" -v`

Expected: FAIL，因为当前日志只含包装异常类型。

- [ ] **Step 3: 写入安全字段并保持错误响应不变**

```python
logger.warning(
    "contract_review_pdf_generation_failed task_id=%s error_type=%s "
    "failure_stage=%s cause_type=%s return_code=%s",
    task_id, exc.__class__.__name__, exc.failure_stage,
    exc.cause_type or "none", exc.return_code if exc.return_code is not None else "none",
)
```

renderer unavailable 分支使用同一安全字段集合。不得把 `%s` 绑定到 `exc` 或 `str(exc)`。

- [ ] **Step 4: 运行 API 测试并确认 GREEN**

Run: `cd backend; uv run pytest tests/test_contract_review_report_api.py -v`

Expected: 全部通过，原 500/503 错误码不变。

---

### Task 4: 全量验证与 Windows reload 回归

**Files:**
- Inspect: `backend/app/services/contract_review_pdf.py`
- Inspect: `backend/app/core/logging.py`
- Inspect: `backend/app/api/v1/analysis.py`

**Interfaces:**
- Consumes: Tasks 1-3 的最终实现。
- Produces: 可复查的测试和运行证据。

- [ ] **Step 1: 运行静态检查与后端全量测试**

Run: `cd backend; uv run ruff check .`

Expected: `All checks passed!`

Run: `cd backend; uv run pytest`

Expected: 全部测试通过；只允许项目原有的第三方弃用 warning。

- [ ] **Step 2: 在 Windows Selector loop 下直接回放已确认的 LangSmith 输出**

使用只读 LangSmith run `019f5a90-af4a-7870-8b71-4e15619e88c6`，加载 `report_response` 后在 `_WindowsSelectorEventLoop` 中调用 renderer。不得打印合同输入或模型原始输出。

Expected: 生成 `%PDF-` 内容，且不再出现 `NotImplementedError`。

- [ ] **Step 3: 验证 reload 服务链路与日志脱敏**

在现有 Windows `uvicorn --reload` 服务中，以测试 stub 或安全样本触发 PDF 生成边界；检查请求成功或至少 renderer 成功进入持久化边界。构造带签名查询参数的 httpx 日志记录，确认日志文件不包含查询参数值。

- [ ] **Step 4: 检查变更范围**

Run: `git diff --check`

Run: `git status --short`

Expected: 仅包含本计划列出的后端代码、测试和计划文档，以及用户原有未提交内容；不包含 `.env`、`.tools/`、上传文件、模型输出或真实案件材料。
