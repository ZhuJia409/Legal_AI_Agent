import asyncio
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from jinja2 import DictLoader, UndefinedError
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.contract_background import (
    BackgroundCard,
    ContractBackgroundResponse,
    EvidenceText,
    RelatedDocument,
    ReviewPitfall,
    SourceRef,
)
from app.schemas.contract_review import (
    ContractReviewReport,
    ContractReviewReportResponse,
    ContractTypeSelection,
    ReportDocumentInfo,
    ReviewFinding,
    ReviewModuleError,
    ReviewModuleResult,
)
from app.services.contract_review_pdf import (
    ContractReviewPdfRenderer,
    PdfRendererUnavailableError,
    ReportPdfGenerationError,
    TectonicCompiler,
    build_report_context,
    build_report_filename,
    create_latex_environment,
    latex_escape,
    latex_escape_breakable_filename,
)


def _report_response(*, status: str = "complete") -> ContractReviewReportResponse:
    findings = [
        ReviewFinding(
            finding_id="general-001",
            module="general_substantive",
            risk_level="low",
            contract_location="第九条",
            issue="通知地址未确认",
            basis="通知地址栏为空。",
            impact="可能影响送达认定。",
            suggestion="补充有效通知地址。",
            negotiation_strategy="签署前由双方书面确认。",
        ),
        ReviewFinding(
            finding_id="party-001",
            module="party_qualification",
            risk_level="fatal",
            contract_location="合同首部",
            issue="签约主体无法确认",
            basis="统一社会信用代码缺失。",
            impact="可能无法确认合同相对方。",
            suggestion="核验营业执照并补全主体信息。",
            negotiation_strategy="将主体核验作为签署前置条件。",
            source_refs=[
                SourceRef(
                    paragraph_id="p0001",
                    document_name="采购合同.pdf",
                    clause_path="合同首部",
                    quote="乙方：某某公司",
                )
            ],
        ),
        ReviewFinding(
            finding_id="special-001",
            module="contract_type_special",
            risk_level="medium",
            contract_location="第五条",
            issue="验收标准不清",
            basis="仅约定验收合格，未列明标准。",
            impact="可能产生交付争议。",
            suggestion="补充可核验的验收指标。",
            negotiation_strategy="把验收清单作为合同附件。",
        ),
        ReviewFinding(
            finding_id="form-001",
            module="form_structure",
            risk_level="high",
            contract_location="签署页",
            issue="签署日期缺失",
            basis="日期栏为空。",
            impact="可能影响生效时间判断。",
            suggestion="签署时填写完整日期。",
            negotiation_strategy="要求双方同日签署。",
        ),
    ]
    background = ContractBackgroundResponse(
        module="contract_background",
        disclaimer="背景判断仍需法律专业人士复核。",
        summary="本合同用于采购生产设备。",
        background_card=BackgroundCard(
            commercial_purpose=EvidenceText(text="采购生产设备", source_refs=[]),
            party_position=EvidenceText(text="甲方采购、乙方供货", source_refs=[]),
            counterparty_identity=EvidenceText(text=None, source_refs=[]),
            amount_term_scope=EvidenceText(text="总价 100 万元", source_refs=[]),
            business_focus=EvidenceText(text="交付、验收与质保", source_refs=[]),
            urgency_deadline=EvidenceText(text=None, source_refs=[]),
        ),
        contract_category="commercial_transaction",
        related_documents=[RelatedDocument(name="技术规格", status="missing")],
        missing_questions=["乙方完整工商登记信息是什么？"],
        pitfalls=[
            ReviewPitfall(
                name="名实不符",
                risk="暂未发现明显冲突",
                review_action="结合履行资料继续核验",
            )
        ],
    )
    modules = [
        ReviewModuleResult(
            module="party_qualification",
            status="succeeded",
            summary="主体信息需要补充。",
            findings=[findings[1]],
            missing_evidence=["营业执照"],
        ),
        ReviewModuleResult(
            module="related_document_comparison",
            status="failed" if status == "partial" else "skipped",
            summary="缺少可供比对的关联文件。",
            missing_evidence=["盖章版技术附件"],
            error=(
                ReviewModuleError(code="related_parse_error", message="关联文件解析失败")
                if status == "partial"
                else None
            ),
        ),
    ]
    return ContractReviewReportResponse(
        module="contract_review_report",
        task_id="task-abcdef123456",
        status=status,
        review_perspective="party_a",
        background=background,
        contract_types=[
            ContractTypeSelection(
                code="sale",
                label="买卖合同",
                rule_pack="references/sale.md",
                is_primary=True,
                reason="包含设备交付与价款支付安排。",
                source_refs=[],
            )
        ],
        modules=modules,
        report=ContractReviewReport(
            executive_summary="存在主体、签署和验收风险。",
            overall_risk_level="fatal",
            signing_recommendation="do_not_sign",
            preconditions=["完成主体资格核验", "补充验收附件"],
            findings=findings,
            limitations=["未取得乙方营业执照"],
            failed_modules=["related_document_comparison"] if status == "partial" else [],
        ),
        disclaimer="本报告由人工智能辅助生成，必须由法律专业人士复核。",
    )


class CapturingCompiler:
    def __init__(self, content: bytes = b"%PDF-1.7\nfixture") -> None:
        self.content = content
        self.latex_source = ""

    async def compile(self, latex_source: str) -> bytes:
        self.latex_source = latex_source
        return self.content


class RaisingCompiler:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def compile(self, latex_source: str) -> bytes:
        raise self.error


def test_latex_escape_handles_commands_special_characters_chinese_and_newlines() -> None:
    escaped = latex_escape(
        "中文 \\input{evil} $100 & #1_条 ~ ^\n第二段\r\n\x00第三段"
    )

    assert "中文" in escaped
    assert r"\textbackslash{}input\{evil\}" in escaped
    assert r"\$100 \& \#1\_条 \textasciitilde{} \textasciicircum{}" in escaped
    assert escaped.count(r"\par{}") == 2
    assert "\x00" not in escaped
    assert "\\input{evil}" not in escaped


def test_latex_escape_breakable_filename_handles_unbroken_text_and_injection() -> None:
    filename = "a" * 80 + r"_合同\input{secret}.docx"

    escaped = latex_escape_breakable_filename(filename)

    assert escaped.count(r"\allowbreak{}") == len(filename) - 1
    assert r"\_" in escaped
    assert r"\textbackslash{}" in escaped
    assert r"\{" in escaped
    assert r"\}" in escaped
    assert r"\input{secret}" not in escaped


def test_latex_environment_uses_strict_undefined() -> None:
    environment = create_latex_environment(loader=DictLoader({"test": "<< missing >>"}))

    with pytest.raises(UndefinedError):
        environment.get_template("test").render()


def test_report_document_info_requires_timezone_aware_generated_at() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        ReportDocumentInfo(
            filename="报告.pdf",
            size_bytes=10,
            sha256="a" * 64,
            generated_at=datetime(2026, 7, 13, 12, 0),
            download_path="/api/v1/contract-review-reports/task-1/document",
        )


def test_contract_review_response_accepts_legacy_snapshot_without_report_document() -> None:
    payload = _report_response().model_dump(mode="json")
    payload.pop("report_document")

    restored = ContractReviewReportResponse.model_validate(payload)

    assert restored.report_document is None


def test_pdf_settings_have_local_tectonic_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.tectonic_path == ".tools/tectonic/tectonic.exe"
    assert settings.tectonic_timeout_seconds == 90


@pytest.mark.parametrize(
    ("overrides", "field_name"),
    [
        ({"tectonic_path": ""}, "tectonic_path"),
        ({"tectonic_path": "   "}, "tectonic_path"),
        ({"tectonic_timeout_seconds": 0}, "tectonic_timeout_seconds"),
        ({"tectonic_timeout_seconds": -1}, "tectonic_timeout_seconds"),
    ],
)
def test_pdf_settings_reject_invalid_renderer_configuration(
    overrides: dict[str, object],
    field_name: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, **overrides)

    assert field_name in str(exc_info.value)


def test_report_filename_falls_back_for_missing_or_fully_illegal_title() -> None:
    generated_at = datetime(2026, 7, 13, tzinfo=UTC)

    source_fallback = build_report_filename(
        title=None,
        source_filename="采购合同.docx",
        status="complete",
        task_id="task-fallback",
        generated_at=generated_at,
    )
    illegal_fallback = build_report_filename(
        title='<>:"/\\|?*\x00',
        source_filename=None,
        status="complete",
        task_id="task-illegal",
        generated_at=generated_at,
    )

    assert source_fallback == "采购合同_合同审查报告_20260713_taskfall.pdf"
    assert illegal_fallback == "未命名合同_合同审查报告_20260713_taskille.pdf"


@pytest.mark.asyncio
async def test_renderer_generates_complete_filename_and_document_metadata() -> None:
    compiler = CapturingCompiler()
    renderer = ContractReviewPdfRenderer(compiler=compiler)
    generated_at = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)

    generated = await renderer.render(
        _report_response(),
        task_id="task-abcdef123456",
        title="../采购/合同\x00",
        source_filename="采购合同.pdf",
        generated_at=generated_at,
    )
    document = generated.to_document_info("task-abcdef123456")

    assert generated.filename == "采购_合同_合同审查报告_20260713_taskabcd.pdf"
    assert generated.content == b"%PDF-1.7\nfixture"
    assert generated.sha256 == "f581fc87f30296eff11777c3ce1b9a8b7077071ad8abedfcba317fef0c807224"
    assert document.size_bytes == len(generated.content)
    assert document.download_path == (
        "/api/v1/contract-review-reports/task-abcdef123456/document"
    )
    assert document.format == "pdf"
    assert document.content_type == "application/pdf"


@pytest.mark.asyncio
async def test_renderer_defaults_generated_at_to_asia_shanghai() -> None:
    renderer = ContractReviewPdfRenderer(compiler=CapturingCompiler())

    generated = await renderer.render(
        _report_response(),
        task_id="task-timezone",
        title="采购合同",
        source_filename="采购合同.pdf",
    )

    assert generated.generated_at.tzinfo == ZoneInfo("Asia/Shanghai")
    assert generated.generated_at.utcoffset().total_seconds() == 8 * 60 * 60


@pytest.mark.asyncio
async def test_renderer_marks_partial_filename_cover_and_footer() -> None:
    compiler = CapturingCompiler()
    renderer = ContractReviewPdfRenderer(compiler=compiler)

    generated = await renderer.render(
        _report_response(status="partial"),
        task_id="partial-12345678",
        title="采购合同",
        source_filename="采购合同.pdf",
        generated_at=datetime(2026, 7, 13, tzinfo=UTC),
    )

    assert generated.filename == "采购合同_合同审查报告_不完整_20260713_partial1.pdf"
    assert compiler.latex_source.count("不可作为签署依据") >= 2
    assert "部分审查模块未成功完成" in compiler.latex_source


@pytest.mark.asyncio
async def test_renderer_sorts_risks_and_renders_counts_and_unknown_labels() -> None:
    compiler = CapturingCompiler()
    renderer = ContractReviewPdfRenderer(compiler=compiler)

    await renderer.render(
        _report_response(),
        task_id="task-counts",
        title="采购合同",
        source_filename="采购合同.pdf",
        generated_at=datetime(2026, 7, 13, tzinfo=UTC),
    )

    source = compiler.latex_source
    assert source.index("签约主体无法确认") < source.index("签署日期缺失")
    assert source.index("签署日期缺失") < source.index("验收标准不清")
    assert source.index("验收标准不清") < source.index("通知地址未确认")
    assert "致命风险 & 1" in source
    assert "高风险 & 1" in source
    assert "中风险 & 1" in source
    assert "低风险 & 1" in source
    assert "甲方立场" in source
    assert "建议暂不签署" in source
    assert "未从材料确认" in source
    assert "专业法律人士复核" in source
    assert "AI 辅助生成，审查人待律师确认" in source


@pytest.mark.asyncio
async def test_template_contains_only_five_concise_sections() -> None:
    compiler = CapturingCompiler()
    renderer = ContractReviewPdfRenderer(compiler=compiler)

    await renderer.render(
        _report_response(status="partial"),
        task_id="task-template",
        title="采购合同",
        source_filename="采购合同.pdf",
        generated_at=datetime(2026, 7, 13, tzinfo=UTC),
    )

    source = compiler.latex_source
    for section in (
        "一、合同基本信息",
        "二、审查范围与依据",
        "三、重点风险及修改建议",
        "四、综合审查结论",
        "五、附件状态",
    ):
        assert section in source

    assert source.count(r"\reportsection{") == 5
    assert r"\begin{titlepage}" not in source
    assert r"\tableofcontents" not in source
    assert "合同背景审查" not in source
    assert "模块状态、缺失材料与错误" not in source
    assert "审查限制" not in source
    assert "证据引用" not in source
    assert r"\fieldlabel{风险描述：}签约主体无法确认" in source
    assert r"\fieldlabel{法律后果：}可能无法确认合同相对方。" in source
    assert r"\fieldlabel{修改建议：}核验营业执照并补全主体信息。" in source
    assert r"\fieldlabel{谈判策略：}将主体核验作为签署前置条件。" in source
    assert "AI 辅助生成，审查人待律师确认" in source
    assert "related_parse_error" not in source
    assert r"related\_parse\_error" not in source
    assert "关联文件解析失败" not in source
    assert "未接入权威法条及行业惯例核验" in source
    assert "专业法律人士复核" in source
    assert "修改对比版合同 & 未生成" in source
    assert "引用法规清单 & 未单独生成，主要依据已在报告中列示" in source
    assert "主体调查报告 & 未生成或未提供" in source


def test_report_context_limits_findings_bases_and_preconditions() -> None:
    response = _report_response().model_copy(deep=True)
    base_finding = response.report.findings[0]
    response.report.findings = [
        base_finding.model_copy(
            update={
                "finding_id": f"finding-{index:02d}",
                "risk_level": ("low", "medium", "high", "fatal")[index % 4],
                "issue": f"风险事项 {index}",
                "basis": f"主要依据 {index}",
            }
        )
        for index in range(12)
    ]
    response.report.preconditions = [f"签署前提 {index}" for index in range(7)]

    context = build_report_context(
        response,
        task_id="task-context",
        title="采购合同",
        source_filename="采购合同.pdf",
        generated_at=datetime(2026, 7, 13, tzinfo=UTC),
    )

    assert len(context["findings"]) == 10
    assert sum(context["risk_counts"].values()) == 12
    assert context["omitted_findings_count"] == 2
    assert len(context["review_bases"]) == 8
    assert len(context["preconditions"]) == 5
    assert context["contract_number"] == "未从材料确认"
    assert context["contract_parties"] == "未从材料确认"
    assert context["amount_and_term"] == "总价 100 万元"
    assert context["reviewer"] == "AI 辅助生成，审查人待律师确认"


@pytest.mark.asyncio
async def test_untrusted_report_field_is_escaped_by_real_template() -> None:
    compiler = CapturingCompiler()
    renderer = ContractReviewPdfRenderer(compiler=compiler)
    response = _report_response().model_copy(deep=True)
    response.report.findings[0].issue = r"恶意\input{secret} & % $ # _ ~ ^"

    await renderer.render(
        response,
        task_id="task-malicious",
        title="采购合同",
        source_filename="采购合同.pdf",
        generated_at=datetime(2026, 7, 13, tzinfo=UTC),
    )

    assert r"恶意\textbackslash{}input\{secret\}" in compiler.latex_source
    assert r"\& \% \$ \# \_ \textasciitilde{} \textasciicircum{}" in compiler.latex_source
    assert r"\input{secret}" not in compiler.latex_source


@pytest.mark.asyncio
async def test_renderer_wraps_template_errors_with_exception_chain() -> None:
    environment = create_latex_environment(
        loader=DictLoader({"broken.tex.j2": "<< missing_value >>"})
    )
    renderer = ContractReviewPdfRenderer(
        compiler=CapturingCompiler(),
        environment=environment,
        template_name="broken.tex.j2",
    )

    with pytest.raises(ReportPdfGenerationError, match="模板") as exc_info:
        await renderer.render(
            _report_response(),
            task_id="task-template-error",
            title="采购合同",
            source_filename="采购合同.pdf",
            generated_at=datetime(2026, 7, 13, tzinfo=UTC),
        )

    assert isinstance(exc_info.value.__cause__, UndefinedError)


@pytest.mark.asyncio
async def test_renderer_wraps_ordinary_compiler_errors_with_exception_chain() -> None:
    renderer = ContractReviewPdfRenderer(compiler=RaisingCompiler(RuntimeError("boom")))

    with pytest.raises(ReportPdfGenerationError, match="编译") as exc_info:
        await renderer.render(
            _report_response(),
            task_id="task-compiler-error",
            title="采购合同",
            source_filename="采购合同.pdf",
            generated_at=datetime(2026, 7, 13, tzinfo=UTC),
        )

    assert isinstance(exc_info.value.__cause__, RuntimeError)


@pytest.mark.asyncio
async def test_renderer_preserves_specialized_generation_errors() -> None:
    sentinel = PdfRendererUnavailableError(
        "renderer unavailable",
        failure_stage="renderer_unavailable",
    )
    renderer = ContractReviewPdfRenderer(compiler=RaisingCompiler(sentinel))

    with pytest.raises(PdfRendererUnavailableError) as exc_info:
        await renderer.render(
            _report_response(),
            task_id="task-special-error",
            title="采购合同",
            source_filename="采购合同.pdf",
            generated_at=datetime(2026, 7, 13, tzinfo=UTC),
        )

    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_renderer_rejects_compiler_output_without_pdf_header() -> None:
    renderer = ContractReviewPdfRenderer(compiler=CapturingCompiler(b"not-a-pdf"))

    with pytest.raises(ReportPdfGenerationError, match="PDF 文件头"):
        await renderer.render(
            _report_response(),
            task_id="task-invalid",
            title="采购合同",
            source_filename="采购合同.pdf",
            generated_at=datetime(2026, 7, 13, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_tectonic_compiler_uses_threaded_subprocess_without_asyncio_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "tectonic.exe"
    executable.write_bytes(b"fake")
    captured: dict[str, object] = {}

    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("不得依赖 asyncio 子进程")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        output_directory = Path(args[args.index("--outdir") + 1])
        captured["working_directory"] = output_directory
        assert (output_directory / "report.tex").read_text(encoding="utf-8") == "中文正文"
        (output_directory / "report.pdf").write_bytes(b"%PDF-1.7\ncompiled")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_if_called)
    monkeypatch.setattr(subprocess, "run", fake_run)
    repository_root = tmp_path / "repository"
    compiler = TectonicCompiler(
        tectonic_path=executable,
        timeout_seconds=3,
        repository_root=repository_root,
    )

    content = await compiler.compile("中文正文")

    working_directory = captured["working_directory"]
    assert isinstance(working_directory, Path)
    assert captured["args"] == [
        str(executable),
        "--only-cached",
        "--keep-logs",
        "--outdir",
        str(working_directory),
        "report.tex",
    ]
    process_options = captured["kwargs"]
    assert isinstance(process_options, dict)
    assert process_options["cwd"] == str(working_directory)
    assert process_options["stdout"] is subprocess.DEVNULL
    assert process_options["stderr"] is subprocess.DEVNULL
    assert process_options["timeout"] == 3
    assert process_options["check"] is False
    assert process_options["shell"] is False
    assert process_options["env"]["TECTONIC_CACHE_DIR"] == str(
        (repository_root / ".tools" / "tectonic" / "cache").resolve()
    )
    assert content == b"%PDF-1.7\ncompiled"
    assert not working_directory.exists()


@pytest.mark.asyncio
async def test_tectonic_timeout_has_safe_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "tectonic.exe"
    executable.write_bytes(b"fake")

    def raise_timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(
            cmd="tectonic",
            timeout=0.01,
            stderr="完整合同机密不得进入错误或日志".encode(),
        )

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    compiler = TectonicCompiler(tectonic_path=executable, timeout_seconds=0.01)

    with pytest.raises(ReportPdfGenerationError, match="超时") as exc_info:
        await compiler.compile("合同正文")

    assert exc_info.value.failure_stage == "compile_timeout"
    assert exc_info.value.cause_type == "TimeoutExpired"
    assert exc_info.value.return_code is None
    assert "完整合同机密" not in str(exc_info.value)


def test_tectonic_compiler_resolves_relative_path_from_repository_root(tmp_path: Path) -> None:
    compiler = TectonicCompiler(
        tectonic_path=".tools/tectonic/tectonic.exe",
        repository_root=tmp_path,
    )

    assert compiler.executable_path == (
        tmp_path / ".tools" / "tectonic" / "tectonic.exe"
    ).resolve()
    assert compiler.cache_directory == (
        tmp_path / ".tools" / "tectonic" / "cache"
    ).resolve()


def test_tectonic_compiler_preserves_absolute_path(tmp_path: Path) -> None:
    executable = (tmp_path / "bin" / "tectonic.exe").resolve()

    compiler = TectonicCompiler(tectonic_path=executable, repository_root=tmp_path / "unused")

    assert compiler.executable_path == executable


@pytest.mark.asyncio
async def test_tectonic_compiler_reports_missing_executable_as_unavailable(tmp_path: Path) -> None:
    missing = tmp_path / "missing" / "tectonic.exe"
    compiler = TectonicCompiler(tectonic_path=missing)

    with pytest.raises(PdfRendererUnavailableError, match="Tectonic") as exc_info:
        await compiler.compile("safe")

    assert isinstance(exc_info.value.__cause__, FileNotFoundError)
    assert exc_info.value.failure_stage == "renderer_unavailable"
    assert exc_info.value.cause_type == "FileNotFoundError"


@pytest.mark.asyncio
async def test_tectonic_compiler_wraps_process_start_failure_as_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "tectonic.exe"
    executable.write_bytes(b"fake")

    def fail_start(*args: object, **kwargs: object) -> None:
        raise OSError("process launch failed")

    monkeypatch.setattr(subprocess, "run", fail_start)
    compiler = TectonicCompiler(tectonic_path=executable)

    with pytest.raises(PdfRendererUnavailableError) as exc_info:
        await compiler.compile("safe")

    assert isinstance(exc_info.value.__cause__, OSError)
    assert exc_info.value.failure_stage == "process_start"
    assert exc_info.value.cause_type == "OSError"


@pytest.mark.asyncio
async def test_tectonic_compiler_never_exposes_nonzero_exit_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "tectonic.exe"
    executable.write_bytes(b"fake")
    def fail_compile(
        args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(subprocess, "run", fail_compile)
    compiler = TectonicCompiler(tectonic_path=executable)

    with pytest.raises(ReportPdfGenerationError, match="退出码 1") as exc_info:
        await compiler.compile("原始 LaTeX 与合同正文不得进入错误消息")

    assert str(exc_info.value) == "Tectonic 编译失败（退出码 1）"
    assert "完整合同机密" not in str(exc_info.value)
    assert exc_info.value.failure_stage == "compile_exit"
    assert exc_info.value.return_code == 1


@pytest.mark.asyncio
async def test_tectonic_compiler_cleans_temp_dir_after_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "tectonic.exe"
    executable.write_bytes(b"fake")
    captured_directory: Path | None = None

    def timeout(*args: object, **kwargs: object) -> None:
        nonlocal captured_directory
        captured_directory = Path(str(kwargs["cwd"]))
        raise subprocess.TimeoutExpired(cmd="tectonic", timeout=0.01)

    monkeypatch.setattr(subprocess, "run", timeout)
    compiler = TectonicCompiler(tectonic_path=executable, timeout_seconds=0.01)

    with pytest.raises(ReportPdfGenerationError, match="超时") as exc_info:
        await compiler.compile("safe")

    assert isinstance(exc_info.value.__cause__, subprocess.TimeoutExpired)
    assert exc_info.value.failure_stage == "compile_timeout"
    assert captured_directory is not None
    assert not captured_directory.exists()


@pytest.mark.asyncio
async def test_tectonic_compiler_cancellation_propagates_and_worker_cleans_temp_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "tectonic.exe"
    executable.write_bytes(b"fake")
    captured_directory: Path | None = None
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def finish_after_release(
        args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal captured_directory
        captured_directory = Path(str(kwargs["cwd"]))
        started.set()
        assert release.wait(timeout=1)
        (captured_directory / "report.pdf").write_bytes(b"%PDF-1.7\ncompiled")
        finished.set()
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", finish_after_release)
    compiler = TectonicCompiler(tectonic_path=executable)
    task = asyncio.create_task(compiler.compile("取消时也必须清理"))
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    release.set()
    assert await asyncio.to_thread(finished.wait, 1)
    assert captured_directory is not None
    for _ in range(20):
        if not captured_directory.exists():
            break
        await asyncio.sleep(0.01)
    assert not captured_directory.exists()


@pytest.mark.asyncio
async def test_tectonic_compiler_unexpected_runner_error_is_safely_wrapped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "tectonic.exe"
    executable.write_bytes(b"fake")
    runner_error = RuntimeError("通信异常中的合同秘密")
    captured_directory: Path | None = None

    def fail_runner(*args: object, **kwargs: object) -> None:
        nonlocal captured_directory
        captured_directory = Path(str(kwargs["cwd"]))
        raise runner_error

    monkeypatch.setattr(subprocess, "run", fail_runner)
    compiler = TectonicCompiler(tectonic_path=executable)

    with pytest.raises(ReportPdfGenerationError) as exc_info:
        await compiler.compile("通信异常时也必须清理")

    assert str(exc_info.value) == "Tectonic 编译通信失败"
    assert exc_info.value.__cause__ is runner_error
    assert "合同秘密" not in str(exc_info.value)
    assert exc_info.value.failure_stage == "compile_exit"
    assert exc_info.value.cause_type == "RuntimeError"
    assert captured_directory is not None
    assert not captured_directory.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pdf_content", "message"),
    [(b"", "空"), (b"not-pdf", "PDF 文件头")],
)
async def test_tectonic_compiler_rejects_invalid_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pdf_content: bytes,
    message: str,
) -> None:
    executable = tmp_path / "tectonic.exe"
    executable.write_bytes(b"fake")

    def fake_run(
        args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        working_directory = Path(str(kwargs["cwd"]))
        (working_directory / "report.pdf").write_bytes(pdf_content)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    compiler = TectonicCompiler(tectonic_path=executable)

    with pytest.raises(ReportPdfGenerationError, match=message) as exc_info:
        await compiler.compile("safe")

    assert exc_info.value.failure_stage == "output_validation"


def test_setup_tectonic_script_pins_release_checksum_and_runs_chinese_smoke() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    script = (repository_root / "scripts" / "setup-tectonic.ps1").read_text(encoding="utf-8")

    assert "0.15.0" in script
    assert (
        "https://github.com/tectonic-typesetting/tectonic/releases/download/"
        "tectonic%400.15.0/tectonic-0.15.0-x86_64-pc-windows-msvc.zip"
    ) in script
    assert "1D6BB76F049C8A3774F6E9D66E4B04E1A8C3DCB37527B6B41B7E894328E7BF29" in script
    assert "Get-FileHash" in script
    assert '$PSBoundParameters.ContainsKey("Version")' in script
    assert "tectonic%40$Version/tectonic-$Version-x86_64-pc-windows-msvc.zip" in script
    assert "ctexart" in script
    assert "Fandol" in script
    assert r"\Huge" in script
    assert r"\scriptsize" in script
    assert "$A_1 + B^2$" in script
    assert "$M_1 + N^2$" in script
    assert "%PDF-" in script
    assert "--outdir $smokeDirectory $smokeTexPath" in script
    assert "--only-cached --keep-logs --outdir $smokeDirectory $smokeTexPath" in script
    assert "Remove-Item -LiteralPath $smokePdfPath" in script
    assert '$env:TECTONIC_CACHE_DIR = $cacheDirectory' in script
    assert '[System.IO.File]::Replace(' in script
    assert '[System.IO.File]::Move(' in script
    assert "stagedExecutable" in script
    assert "stagedSha256" in script
    assert "sourceSha256" in script
    direct_target_copy = (
        "Copy-Item -LiteralPath $downloadedExecutable.FullName "
        "-Destination $targetExecutable"
    )
    assert direct_target_copy not in script

    readme = (repository_root / "scripts" / "README.md").read_text(encoding="utf-8")
    assert "运行时仅使用已预热缓存" in readme


@pytest.mark.asyncio
async def test_real_tectonic_compiles_current_chinese_report_template_when_installed() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    executable = repository_root / ".tools" / "tectonic" / "tectonic.exe"
    if not executable.is_file():
        pytest.skip("本地未安装 Tectonic，运行 scripts/setup-tectonic.ps1 后执行真实集成测试")

    renderer = ContractReviewPdfRenderer(
        compiler=TectonicCompiler(tectonic_path=executable, timeout_seconds=90)
    )
    generated = await renderer.render(
        _report_response(status="partial"),
        task_id="real-tectonic-12345678",
        title="办公 IT 设备采购合同",
        source_filename=f"{'a' * 100}_采购合同_办公IT设备采购.docx",
        generated_at=datetime(2026, 7, 13, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert generated.content.startswith(b"%PDF-")
    assert len(generated.content) > 1_000
