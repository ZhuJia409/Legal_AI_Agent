from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.schemas.case_analysis import DocumentDraftStageResult
from app.services import case_analysis_document as document_module

CaseAnalysisDocumentRenderer = document_module.CaseAnalysisDocumentRenderer


class CapturingCompiler:
    def __init__(self, content: bytes = b"%PDF-1.7\ncase") -> None:
        self.content = content
        self.latex_source = ""

    async def compile(self, latex_source: str) -> bytes:
        self.latex_source = latex_source
        return self.content


def _draft_stage(*, status: str = "needs_input") -> DocumentDraftStageResult:
    return DocumentDraftStageResult.model_validate(
        {
            "stage": "document_draft",
            "status": status,
            "summary": "已生成精简文书表单。",
            "missing_information": ["代理立场"],
            "requires_human_review": True,
            "error": None,
            "draft_title": "中立案件处理意见（草稿）",
            "draft_sections": [],
            "quality_checks": ["律师复核"],
            "document_form": {
                "report_title": "案件处理方案与文书草稿",
                "case_summary": "双方就婚约期间款项性质及返还范围存在争议。",
                "strategies": [
                    {
                        "mode": "balanced",
                        "objective": "补强证据并保留协商与诉讼路径。",
                        "actions": ["核验转账凭证", "固定沟通记录"],
                        "prerequisites": ["明确代理立场"],
                        "risks": ["款项性质证据不足"],
                    }
                ],
                "draft_title": "中立案件处理意见（草稿）",
                "draft_purpose": "供律师确定后续谈判或诉讼方案。",
                "key_facts": [
                    {
                        "text": r"双方未登记结婚，款项含特殊字符 & 100% \input{bad}。",
                        "source_refs": [
                            {"paragraph_id": "p0002", "quote": "不应显示的完整原文"}
                        ],
                    }
                ],
                "core_positions_or_requests": ["款项性质需结合给付目的判断。"],
                "recommended_actions": ["补充银行流水"],
                "missing_information": ["代理立场"],
                "lawyer_review_items": ["核对管辖和请求范围"],
            },
        }
    )


@pytest.mark.asyncio
async def test_case_document_renders_four_section_pdf_from_validated_form() -> None:
    assert hasattr(document_module, "CaseDocumentGenerationError")
    compiler = CapturingCompiler()
    renderer = CaseAnalysisDocumentRenderer(compiler=compiler)

    generated = await renderer.render(
        analysis_id="123e4567-e89b-12d3-a456-426614174000",
        title="婚约财产纠纷",
        status="partial",
        risk_level="high",
        draft_stage=_draft_stage(),
        generated_at=datetime(2026, 7, 15, tzinfo=UTC),
    )

    source = compiler.latex_source
    assert generated.filename.endswith(".pdf")
    assert generated.content_type == "application/pdf"
    assert generated.content.startswith(b"%PDF-")
    for section in (
        "一、案件概览",
        "二、条件化处理方案",
        "三、文书草稿",
        "四、待补与复核",
    ):
        assert section in source
    assert source.count(r"\reportsection{") == 4
    assert r"\begin{titlepage}" not in source
    assert r"\tableofcontents" not in source
    assert "tcolorbox" not in source
    assert "材料第 2 段" in source
    assert "不应显示的完整原文" not in source
    assert r"\& 100\% \textbackslash{}input\{bad\}" in source
    assert r"\input{bad}" not in source
    assert source.count("不可直接提交或作为诉讼决策依据") >= 2
    assert "专业律师复核" in source


@pytest.mark.asyncio
async def test_case_document_rejects_non_pdf_compiler_output() -> None:
    error_type = getattr(document_module, "CaseDocumentGenerationError", RuntimeError)
    renderer = CaseAnalysisDocumentRenderer(compiler=CapturingCompiler(b"not-pdf"))

    with pytest.raises(error_type, match="PDF"):
        await renderer.render(
            analysis_id="analysis-invalid-pdf",
            title=None,
            status="complete",
            risk_level="medium",
            draft_stage=_draft_stage(status="succeeded"),
        )


@pytest.mark.asyncio
async def test_case_document_defaults_generated_at_to_asia_shanghai() -> None:
    renderer = CaseAnalysisDocumentRenderer(compiler=CapturingCompiler())

    generated = await renderer.render(
        analysis_id="analysis-timezone",
        title="案件",
        status="complete",
        risk_level="medium",
        draft_stage=_draft_stage(status="succeeded"),
    )

    assert generated.generated_at.utcoffset() is not None
    assert generated.generated_at.utcoffset().total_seconds() == 8 * 60 * 60
