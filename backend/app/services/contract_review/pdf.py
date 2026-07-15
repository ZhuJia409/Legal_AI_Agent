"""合同审查报告的确定性 LaTeX 渲染与 PDF 文档组装。"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from jinja2 import Environment, TemplateError

from app.schemas.contract_review import (
    ContractPdfDocument,
    ContractPdfFinding,
    ContractReviewReportResponse,
    ReportDocumentInfo,
    ReviewFinding,
)
from app.schemas.contract_review.background import SourceRef
from app.services.pdf_runtime import (
    PdfRendererUnavailableError,
    ReportPdfCompiler,
    ReportPdfGenerationError,
    TectonicCompiler,
    create_latex_environment,
    latex_escape,
    latex_escape_breakable_filename,
)

__all__ = [
    "ContractReviewPdfRenderer",
    "GeneratedReportPdf",
    "PdfRendererUnavailableError",
    "ReportPdfCompiler",
    "ReportPdfGenerationError",
    "TectonicCompiler",
    "build_report_context",
    "build_report_filename",
    "create_latex_environment",
    "latex_escape",
    "latex_escape_breakable_filename",
]

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
    pdf_form: ContractPdfDocument,
    task_id: str,
    title: str | None,
    source_filename: str | None,
    generated_at: datetime,
) -> dict[str, object]:
    """把 Pydantic 响应整理为只含展示字段的确定性模板上下文。"""

    # 风险统计覆盖完整审查结果，展示内容只采用经服务端核验的 Agent 表单。
    sorted_findings = sorted(
        response.report.findings,
        key=lambda finding: (_RISK_ORDER[finding.risk_level], finding.finding_id),
    )
    risk_counts = {level: 0 for level in _RISK_ORDER}
    for finding in sorted_findings:
        risk_counts[finding.risk_level] += 1

    # 依据从现有发现中确定性提取，去重且不允许模板层自行补写法律依据。
    review_bases: list[str] = []
    for finding in sorted_findings:
        basis = finding.basis.strip()
        if basis and basis not in review_bases:
            review_bases.append(basis)
        if len(review_bases) == 8:
            break

    primary_type = next(
        (item for item in response.contract_types if item.is_primary),
        response.contract_types[0] if response.contract_types else None,
    )
    background_card = response.background.background_card

    return {
        "task_id": _known_text(task_id),
        "title": _known_text(title),
        "source_filename": _known_text(source_filename),
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M %z"),
        "status": response.status,
        "status_label": "完整报告" if response.status == "complete" else "不完整报告",
        "partial_warning": "部分审查模块未成功完成，本报告不可作为签署依据。",
        "review_perspective_label": _PERSPECTIVE_LABELS[response.review_perspective],
        "contract_number": "未从材料确认",
        "contract_type_label": _known_text(
            primary_type.label
            if primary_type
            else _CATEGORY_LABELS[response.background.contract_category]
        ),
        "contract_parties": _known_text(background_card.counterparty_identity.text),
        "amount_and_term": _known_text(background_card.amount_term_scope.text),
        "reviewer": "AI 辅助生成，审查人待律师确认",
        "completed_modules": [
            _MODULE_LABELS[item.module]
            for item in response.modules
            if item.status == "succeeded"
        ],
        "review_bases": review_bases,
        "scope_warning": (
            "部分审查模块未完成，以下内容仅反映已完成范围。"
            if response.status == "partial"
            else None
        ),
        "executive_summary": _known_text(pdf_form.executive_conclusion),
        "overall_risk_label": _RISK_LABELS[response.report.overall_risk_level],
        "signing_recommendation_label": _SIGNING_LABELS[
            response.report.signing_recommendation
        ],
        "risk_counts": risk_counts,
        "findings": [_pdf_finding_context(item) for item in pdf_form.priority_findings],
        "omitted_findings_count": max(
            0,
            len(sorted_findings) - len(pdf_form.priority_findings),
        ),
        "preconditions": [_known_text(item) for item in pdf_form.signing_preconditions],
        "pending_confirmations": [
            _known_text(item) for item in pdf_form.pending_confirmations
        ],
        "lawyer_review_items": [
            _known_text(item) for item in pdf_form.lawyer_review_items
        ],
        "attachments": [
            {"name": "修改对比版合同", "status": "未生成"},
            {
                "name": "引用法规清单",
                "status": "未单独生成，主要依据已在报告中列示",
            },
            {"name": "主体调查报告", "status": "未生成或未提供"},
        ],
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
        pdf_form: ContractPdfDocument,
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
            pdf_form=pdf_form,
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


def _pdf_finding_context(finding: ContractPdfFinding) -> dict[str, object]:
    return {
        "finding_id": _known_text(finding.finding_id),
        "risk_level": finding.risk_level,
        "risk_label": _RISK_LABELS[finding.risk_level],
        "contract_location": _known_text(finding.contract_location),
        "issue": _known_text(finding.display_title),
        "impact": _known_text(finding.legal_consequence),
        "suggestion": _known_text(finding.revision_advice),
        "negotiation_strategy": _known_text(finding.negotiation_strategy),
        "risk_description": _known_text(finding.risk_description),
    }
