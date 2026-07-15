from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, TemplateError

from app.schemas.case_analysis import (
    AnalysisStatus,
    CaseDraftDocumentInfo,
    DocumentDraftStageResult,
    RiskLevel,
)
from app.services.pdf_runtime import ReportPdfCompiler, create_latex_environment

PDF_CONTENT_TYPE = "application/pdf"
_MODE_LABELS = {
    "aggressive": "激进方案",
    "balanced": "稳健方案",
    "conservative": "保守方案",
}
_RISK_LABELS = {"unknown": "待评估", "low": "低", "medium": "中", "high": "高"}


class CaseDocumentGenerationError(RuntimeError):
    """案件文书模板或 PDF 编译失败。"""


@dataclass(frozen=True, slots=True)
class GeneratedCaseDocument:
    filename: str
    content_type: str
    content: bytes
    sha256: str
    generated_at: datetime

    def to_document_info(self, analysis_id: str) -> CaseDraftDocumentInfo:
        document_format = "pdf" if self.content_type == PDF_CONTENT_TYPE else "docx"
        return CaseDraftDocumentInfo(
            format=document_format,
            filename=self.filename,
            content_type=self.content_type,
            size_bytes=len(self.content),
            sha256=self.sha256,
            generated_at=self.generated_at,
            download_path=f"/api/v1/case-analyses/{analysis_id}/document",
        )


class CaseAnalysisDocumentRenderer:
    """把文书 Agent 的严格表单填入固定 LaTeX 模板并编译为 PDF。"""

    def __init__(
        self,
        *,
        compiler: ReportPdfCompiler,
        environment: Environment | None = None,
        template_name: str = "case_analysis_document.tex.j2",
    ) -> None:
        self._compiler = compiler
        self._environment = environment or create_latex_environment()
        self._template_name = template_name

    async def render(
        self,
        *,
        analysis_id: str,
        title: str | None,
        status: AnalysisStatus,
        risk_level: RiskLevel,
        draft_stage: DocumentDraftStageResult,
        generated_at: datetime | None = None,
    ) -> GeneratedCaseDocument:
        form = draft_stage.document_form
        if form is None:
            raise CaseDocumentGenerationError("案件 PDF 缺少已验证的文书表单")
        resolved_generated_at = generated_at or datetime.now(ZoneInfo("Asia/Shanghai"))
        if (
            resolved_generated_at.tzinfo is None
            or resolved_generated_at.utcoffset() is None
        ):
            raise ValueError("generated_at must include timezone")

        strategies = sorted(
            form.strategies,
            key=lambda item: ("aggressive", "balanced", "conservative").index(
                item.mode
            ),
        )
        context = {
            "title": title.strip() if title and title.strip() else "未命名案件",
            "status": status,
            "status_label": "完整" if status == "complete" else "材料不完整",
            "partial_warning": "材料不完整，不可直接提交或作为诉讼决策依据。",
            "risk_label": _RISK_LABELS[risk_level],
            "generated_at": resolved_generated_at.strftime("%Y-%m-%d"),
            "form": {
                "report_title": form.report_title,
                "case_summary": form.case_summary,
                "strategies": [
                    {
                        "mode_label": _MODE_LABELS[item.mode],
                        "objective": item.objective,
                        "actions": item.actions,
                        "prerequisites": item.prerequisites,
                        "risks": item.risks,
                    }
                    for item in strategies
                ],
                "draft_title": form.draft_title,
                "draft_purpose": form.draft_purpose,
                "key_facts": [
                    {
                        "text": item.text,
                        "references": [
                            _paragraph_label(ref.paragraph_id)
                            for ref in item.source_refs
                        ],
                    }
                    for item in form.key_facts
                ],
                "core_positions_or_requests": form.core_positions_or_requests,
                "recommended_actions": form.recommended_actions,
                "missing_information": list(
                    dict.fromkeys(
                        [
                            *form.missing_information,
                            *draft_stage.missing_information,
                        ]
                    )
                )[:5],
                "lawyer_review_items": form.lawyer_review_items,
            },
        }
        try:
            latex_source = self._environment.get_template(self._template_name).render(
                **context
            )
        except TemplateError as exc:
            raise CaseDocumentGenerationError("案件 PDF 模板渲染失败") from exc
        try:
            content = await self._compiler.compile(latex_source)
        except Exception as exc:
            raise CaseDocumentGenerationError("案件 PDF 编译失败") from exc
        if not content.startswith(b"%PDF-"):
            raise CaseDocumentGenerationError("案件 PDF 编译结果无效")

        safe_title = self._safe_title(title)
        return GeneratedCaseDocument(
            filename=(
                f"{safe_title}_案件处理方案与文书草稿_{analysis_id[:8]}.pdf"
            ),
            content_type=PDF_CONTENT_TYPE,
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            generated_at=resolved_generated_at,
        )

    @staticmethod
    def _safe_title(title: str | None) -> str:
        normalized = re.sub(r'[\\/:*?"<>|\r\n]+', "_", (title or "未命名案件").strip())
        return Path(normalized[:60] or "未命名案件").name


def _paragraph_label(paragraph_id: str) -> str:
    number = int(paragraph_id.removeprefix("p"))
    return f"材料第 {number} 段"
