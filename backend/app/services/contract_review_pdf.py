"""合同审查报告的 LaTeX 渲染核心。

本模块只负责可信结构化数据到 LaTeX/PDF 的转换；具体编译器由调用方注入，
便于运行时隔离 Tectonic 边界，也便于单元测试避免依赖本地二进制程序。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote
from zoneinfo import ZoneInfo

from jinja2 import BaseLoader, Environment, FileSystemLoader, StrictUndefined, TemplateError

from app.schemas.contract_background import SourceRef
from app.schemas.contract_review import (
    ContractReviewReportResponse,
    ReportDocumentInfo,
    ReviewFinding,
)

_RISK_ORDER = {"fatal": 0, "high": 1, "medium": 2, "low": 3}
_RISK_LABELS = {"fatal": "致命风险", "high": "高风险", "medium": "中风险", "low": "低风险"}
_PERSPECTIVE_LABELS = {"neutral": "中立立场", "party_a": "甲方立场", "party_b": "乙方立场"}
_SIGNING_LABELS = {
    "do_not_sign": "建议暂不签署",
    "conditional": "满足前提后再签署",
    "can_sign_after_review": "专业复核后可签署",
}
_MODULE_LABELS = {
    "party_qualification": "主体资格审查",
    "form_structure": "形式与结构审查",
    "general_substantive": "通用实质审查",
    "related_document_comparison": "关联文件比对",
    "contract_type_special": "合同类型专项审查",
}
_MODULE_STATUS_LABELS = {"succeeded": "已完成", "failed": "失败", "skipped": "已跳过"}
_CATEGORY_LABELS = {
    "commercial_transaction": "商事交易",
    "service_entrustment": "服务与委托",
    "construction_project": "建设工程",
    "technology_data_ip": "技术、数据与知识产权",
    "finance_guarantee": "金融与担保",
    "investment_ma": "投资并购",
    "labor_hr": "劳动人事",
    "framework_cooperation": "框架合作",
    "other_unknown": "其他或待确认",
}
_BACKGROUND_FIELDS = (
    ("commercial_purpose", "交易目的"),
    ("party_position", "双方立场"),
    ("counterparty_identity", "主体身份与关系"),
    ("amount_term_scope", "金额、期限与范围"),
    ("business_focus", "业务关注点"),
    ("urgency_deadline", "紧迫性与截止日期"),
)


class ReportPdfGenerationError(RuntimeError):
    """报告模板渲染或 PDF 结果校验失败。"""

    def __init__(
        self,
        message: str,
        *,
        failure_stage: str,
        cause_type: str | None = None,
        return_code: int | None = None,
    ) -> None:
        # 仅携带可安全进入日志的分类信息，不保存合同、LaTeX 或编译器输出。
        super().__init__(message)
        self.failure_stage = failure_stage
        self.cause_type = cause_type
        self.return_code = return_code


class PdfRendererUnavailableError(ReportPdfGenerationError):
    """Tectonic 不存在或无法启动，调用方可将其映射为 503。"""


class ReportPdfCompiler(Protocol):
    """外部 PDF 编译边界；实现方不得把合同正文写入不受控日志。"""

    async def compile(self, latex_source: str) -> bytes: ...


class TectonicCompiler:
    """在隔离临时目录中调用本地 Tectonic，且不开放 shell 解释边界。"""

    def __init__(
        self,
        *,
        tectonic_path: str | Path = ".tools/tectonic/tectonic.exe",
        timeout_seconds: float = 90,
        repository_root: Path | None = None,
        cache_directory: str | Path | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        resolved_root = repository_root or Path(__file__).resolve().parents[3]
        configured_path = Path(tectonic_path).expanduser()
        self._executable_path = (
            configured_path
            if configured_path.is_absolute()
            else resolved_root / configured_path
        ).resolve()
        configured_cache = Path(cache_directory or ".tools/tectonic/cache").expanduser()
        self._cache_directory = (
            configured_cache
            if configured_cache.is_absolute()
            else resolved_root / configured_cache
        ).resolve()
        self._timeout_seconds = timeout_seconds

    @property
    def executable_path(self) -> Path:
        """暴露最终路径便于启动诊断；相对配置始终锚定仓库根目录。"""

        return self._executable_path

    @property
    def cache_directory(self) -> Path:
        """项目缓存固定在仓库工具目录，避免依赖具体服务账号的用户缓存。"""

        return self._cache_directory

    async def compile(self, latex_source: str) -> bytes:
        # Windows reload/multi-worker 使用 SelectorEventLoop，需在线程中隔离同步子进程边界。
        return await asyncio.to_thread(self._compile_sync, latex_source)

    def _compile_sync(self, latex_source: str) -> bytes:
        if not self._executable_path.is_file():
            missing_error = FileNotFoundError(self._executable_path)
            raise PdfRendererUnavailableError(
                "Tectonic PDF 渲染器不可用",
                failure_stage="renderer_unavailable",
                cause_type=missing_error.__class__.__name__,
            ) from missing_error

        # 临时目录退出即清理 LaTeX、日志和辅助文件，避免合同正文残留在工作树。
        with tempfile.TemporaryDirectory(prefix="contract-review-pdf-") as temp_dir:
            working_directory = Path(temp_dir)
            source_path = working_directory / "report.tex"
            output_path = working_directory / "report.pdf"
            source_path.write_text(latex_source, encoding="utf-8")
            process_environment = os.environ.copy()
            process_environment["TECTONIC_CACHE_DIR"] = str(self._cache_directory)

            command = [
                str(self._executable_path),
                "--only-cached",
                "--keep-logs",
                "--outdir",
                str(working_directory),
                "report.tex",
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(working_directory),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=process_environment,
                    timeout=self._timeout_seconds,
                    check=False,
                    shell=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ReportPdfGenerationError(
                    "合同审查报告 PDF 编译超时",
                    failure_stage="compile_timeout",
                    cause_type=exc.__class__.__name__,
                ) from exc
            except OSError as exc:
                raise PdfRendererUnavailableError(
                    "Tectonic PDF 渲染器无法启动",
                    failure_stage="process_start",
                    cause_type=exc.__class__.__name__,
                ) from exc
            except Exception as exc:
                # 未知 runner 异常只保留类型，避免异常原文携带合同或命令输出进入日志。
                raise ReportPdfGenerationError(
                    "Tectonic 编译通信失败",
                    failure_stage="compile_exit",
                    cause_type=exc.__class__.__name__,
                ) from exc

            if completed.returncode != 0:
                raise ReportPdfGenerationError(
                    f"Tectonic 编译失败（退出码 {completed.returncode}）",
                    failure_stage="compile_exit",
                    return_code=completed.returncode,
                )
            if not output_path.is_file():
                raise ReportPdfGenerationError(
                    "Tectonic 未生成报告 PDF 文件",
                    failure_stage="output_validation",
                )

            content = output_path.read_bytes()
            if not content:
                raise ReportPdfGenerationError(
                    "Tectonic 生成了空的报告 PDF 文件",
                    failure_stage="output_validation",
                )
            if not content.startswith(b"%PDF-"):
                raise ReportPdfGenerationError(
                    "Tectonic 输出缺少有效的 PDF 文件头",
                    failure_stage="output_validation",
                )
            return content


@dataclass(frozen=True, slots=True)
class GeneratedReportPdf:
    filename: str
    content_type: str
    content: bytes
    sha256: str
    generated_at: datetime

    def to_document_info(self, task_id: str) -> ReportDocumentInfo:
        """生成不含二进制内容、可安全进入 API 响应的文档元数据。"""

        encoded_task_id = quote(task_id, safe="")
        return ReportDocumentInfo(
            filename=self.filename,
            size_bytes=len(self.content),
            sha256=self.sha256,
            generated_at=self.generated_at,
            download_path=f"/api/v1/contract-review-reports/{encoded_task_id}/document",
        )


def latex_escape(value: object) -> str:
    """把不可信文本转换为普通 LaTeX 文本，禁止注入命令或环境。"""

    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "#": r"\#",
        "%": r"\%",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "\n": r"\par{}",
        "\t": "    ",
    }
    escaped: list[str] = []
    for character in text:
        if character in replacements:
            escaped.append(replacements[character])
            continue
        # Cc/Cf 等控制字符可能改变编译行为；换行与制表符已在上方受控处理。
        if unicodedata.category(character).startswith("C"):
            continue
        escaped.append(character)
    return "".join(escaped)


def create_latex_environment(*, loader: BaseLoader | None = None) -> Environment:
    """创建与 LaTeX 定界符隔离、缺字段即失败的 Jinja2 环境。"""

    template_loader = loader or FileSystemLoader(
        Path(__file__).resolve().parents[1] / "templates"
    )
    environment = Environment(
        loader=template_loader,
        undefined=StrictUndefined,
        autoescape=False,
        block_start_string="<%",
        block_end_string="%>",
        variable_start_string="<<",
        variable_end_string=">>",
        comment_start_string="<#",
        comment_end_string="#>",
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["latex_escape"] = latex_escape
    return environment


def build_report_filename(
    *,
    title: str | None,
    source_filename: str | None,
    status: str,
    task_id: str,
    generated_at: datetime,
) -> str:
    """构造稳定且不含路径、控制字符和 Windows 保留字符的报告文件名。"""

    fallback_title = Path(source_filename or "").stem or "未命名合同"
    safe_title = _clean_filename_component(title or fallback_title, fallback="未命名合同")
    short_task_id = re.sub(r"[^A-Za-z0-9]", "", task_id)[:8]
    if not short_task_id:
        short_task_id = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8]
    incomplete_marker = "_不完整" if status == "partial" else ""
    return (
        f"{safe_title}_合同审查报告{incomplete_marker}_"
        f"{generated_at:%Y%m%d}_{short_task_id}.pdf"
    )


def build_report_context(
    response: ContractReviewReportResponse,
    *,
    task_id: str,
    title: str | None,
    source_filename: str | None,
    generated_at: datetime,
) -> dict[str, object]:
    """把 Pydantic 响应整理为只含展示字段的确定性模板上下文。"""

    sorted_findings = sorted(
        response.report.findings,
        key=lambda finding: (_RISK_ORDER[finding.risk_level], finding.finding_id),
    )
    risk_counts = {level: 0 for level in _RISK_ORDER}
    for finding in sorted_findings:
        risk_counts[finding.risk_level] += 1

    background_fields = []
    for field_name, label in _BACKGROUND_FIELDS:
        evidence = getattr(response.background.background_card, field_name)
        background_fields.append(
            {
                "label": label,
                "text": _known_text(evidence.text),
                "source_refs": [_source_ref_context(ref) for ref in evidence.source_refs],
            }
        )

    return {
        "task_id": _known_text(task_id),
        "title": _known_text(title),
        "source_filename": _known_text(source_filename),
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M %z"),
        "status": response.status,
        "status_label": "完整报告" if response.status == "complete" else "不完整报告",
        "partial_warning": "部分审查模块未成功完成，本报告不可作为签署依据。",
        "review_perspective_label": _PERSPECTIVE_LABELS[response.review_perspective],
        "contract_category_label": _CATEGORY_LABELS[response.background.contract_category],
        "contract_types": [
            {
                "label": _known_text(item.label),
                "reason": _known_text(item.reason),
                "is_primary": item.is_primary,
                "source_refs": [_source_ref_context(ref) for ref in item.source_refs],
            }
            for item in response.contract_types
        ],
        "background_summary": _known_text(response.background.summary),
        "background_disclaimer": _known_text(response.background.disclaimer),
        "background_fields": background_fields,
        "related_documents": [
            {
                "name": _known_text(item.name),
                "status_label": "已提供" if item.status == "provided" else "缺失",
            }
            for item in response.background.related_documents
        ],
        "missing_questions": [_known_text(item) for item in response.background.missing_questions],
        "pitfalls": [
            {
                "name": _known_text(item.name),
                "risk": _known_text(item.risk),
                "review_action": _known_text(item.review_action),
                "source_refs": [_source_ref_context(ref) for ref in item.source_refs],
            }
            for item in response.background.pitfalls
        ],
        "executive_summary": _known_text(response.report.executive_summary),
        "overall_risk_label": _RISK_LABELS[response.report.overall_risk_level],
        "signing_recommendation_label": _SIGNING_LABELS[
            response.report.signing_recommendation
        ],
        "risk_counts": risk_counts,
        "findings": [_finding_context(item) for item in sorted_findings],
        "modules": [
            {
                "label": _MODULE_LABELS[item.module],
                "status_label": _MODULE_STATUS_LABELS[item.status],
                "summary": _known_text(item.summary),
                "missing_evidence": [_known_text(value) for value in item.missing_evidence],
                "error_code": _known_text(item.error.code) if item.error else None,
                "error_message": _known_text(item.error.message) if item.error else None,
            }
            for item in response.modules
        ],
        "preconditions": [_known_text(item) for item in response.report.preconditions],
        "limitations": [_known_text(item) for item in response.report.limitations],
        "disclaimer": _known_text(response.disclaimer),
    }


class ContractReviewPdfRenderer:
    """使用严格模板和注入式编译器生成合同审查 PDF。"""

    def __init__(
        self,
        *,
        compiler: ReportPdfCompiler,
        environment: Environment | None = None,
        template_name: str = "contract_review_report.tex.j2",
    ) -> None:
        self._compiler = compiler
        self._environment = environment or create_latex_environment()
        self._template_name = template_name

    async def render(
        self,
        response: ContractReviewReportResponse,
        *,
        task_id: str,
        title: str | None,
        source_filename: str | None,
        generated_at: datetime | None = None,
    ) -> GeneratedReportPdf:
        # 默认使用项目业务时区，显式注入时保留调用方提供的任意 aware datetime。
        resolved_generated_at = generated_at or datetime.now(ZoneInfo("Asia/Shanghai"))
        if resolved_generated_at.tzinfo is None or resolved_generated_at.utcoffset() is None:
            raise ValueError("generated_at must include timezone")

        context = build_report_context(
            response,
            task_id=task_id,
            title=title,
            source_filename=source_filename,
            generated_at=resolved_generated_at,
        )
        try:
            latex_source = self._environment.get_template(self._template_name).render(**context)
        except TemplateError as exc:
            raise ReportPdfGenerationError(
                "合同审查报告模板渲染失败",
                failure_stage="template_render",
                cause_type=exc.__class__.__name__,
            ) from exc

        try:
            content = await self._compiler.compile(latex_source)
        except ReportPdfGenerationError:
            # 专用编译错误及其未来子类保留原始类型，供 API 层精确转换。
            raise
        except Exception as exc:
            raise ReportPdfGenerationError(
                "合同审查报告 PDF 编译失败",
                failure_stage="compile_exit",
                cause_type=exc.__class__.__name__,
            ) from exc
        # 编译器属于外部边界，返回值必须在进入存储层前做最小格式校验。
        if not content.startswith(b"%PDF-"):
            raise ReportPdfGenerationError(
                "报告编译结果缺少有效的 PDF 文件头",
                failure_stage="output_validation",
            )

        filename = build_report_filename(
            title=title,
            source_filename=source_filename,
            status=response.status,
            task_id=task_id,
            generated_at=resolved_generated_at,
        )
        return GeneratedReportPdf(
            filename=filename,
            content_type="application/pdf",
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            generated_at=resolved_generated_at,
        )


def _known_text(value: object | None) -> str:
    if value is None:
        return "未从材料确认"
    normalized = str(value).strip()
    return normalized or "未从材料确认"


def _clean_filename_component(value: str, *, fallback: str) -> str:
    without_controls = "".join(
        character
        for character in value
        if not unicodedata.category(character).startswith("C")
    )
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", without_controls)
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip(" ._")
    return (cleaned[:60].rstrip(" ._") or fallback)


def _source_ref_context(ref: SourceRef) -> dict[str, str]:
    return {
        "document_name": _known_text(ref.document_name),
        "paragraph_id": _known_text(ref.paragraph_id),
        "clause_path": _known_text(ref.clause_path),
        "quote": _known_text(ref.quote),
    }


def _finding_context(finding: ReviewFinding) -> dict[str, object]:
    return {
        "finding_id": _known_text(finding.finding_id),
        "module_label": _MODULE_LABELS[finding.module],
        "risk_label": _RISK_LABELS[finding.risk_level],
        "contract_location": _known_text(finding.contract_location),
        "issue": _known_text(finding.issue),
        "basis": _known_text(finding.basis),
        "impact": _known_text(finding.impact),
        "suggestion": _known_text(finding.suggestion),
        "negotiation_strategy": _known_text(finding.negotiation_strategy),
        "source_refs": [_source_ref_context(ref) for ref in finding.source_refs],
        "requires_human_review": finding.requires_human_review,
    }
