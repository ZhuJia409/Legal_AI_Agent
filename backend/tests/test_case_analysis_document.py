from io import BytesIO

from docx import Document

from app.schemas.case_analysis import (
    DocumentDraftStageResult,
    StrategyStageResult,
)
from app.services.case_analysis_document import CaseAnalysisDocumentRenderer


def _base_stage(stage: str) -> dict[str, object]:
    return {
        "stage": stage,
        "status": "needs_input",
        "summary": "材料有限，需要律师复核。",
        "missing_information": ["代理立场", "原始转账凭证"],
        "requires_human_review": True,
        "error": None,
    }


def test_case_document_only_keeps_concise_stage_seven_and_eight_content() -> None:
    strategy_stage = StrategyStageResult.model_validate(
        {
            **_base_stage("strategy_options"),
            "strategies": [
                {
                    "mode": "balanced",
                    "summary": "先补强证据，再与对方协商或起诉。",
                    "objective": "控制成本并保留诉讼选项。",
                    "steps": ["收集流水", "固定聊天记录", "发出律师函", "起诉"],
                    "prerequisites": ["确认代理立场", "补充转账凭证", "核对管辖"],
                    "risks": ["对方主张赠与", "证据不足", "执行财产不明"],
                    "missing_information": [],
                }
            ],
        }
    )
    draft_stage = DocumentDraftStageResult.model_validate(
        {
            **_base_stage("document_draft"),
            "draft_title": "民事起诉状（草稿）",
            "draft_sections": [
                "文书类型：民事起诉状（待律师确认）",
                "核心事实：双方就婚约期间款项性质存在争议。",
                "核心请求：请求返还相关款项，具体范围待补充。",
            ],
            "quality_checks": ["核对事实", "核对程序", "律师定稿"],
        }
    )

    generated = CaseAnalysisDocumentRenderer().render(
        analysis_id="123e4567-e89b-12d3-a456-426614174000",
        title="婚约财产纠纷",
        risk_level="high",
        strategy_stage=strategy_stage,
        draft_stage=draft_stage,
    )

    paragraphs = [p.text for p in Document(BytesIO(generated.content)).paragraphs]
    text = "\n".join(paragraphs)
    assert generated.filename.endswith(".docx")
    assert "案件处理方案与文书草稿" in text
    assert "三套方案" in text
    assert "民事起诉状（草稿）" in text
    assert "专业律师复核" in text
    assert "起诉" not in paragraphs  # 第 4 个步骤被截断，不独立成段。
    assert "核对管辖" not in text
    assert "执行财产不明" not in text
    assert "案件时间线" not in text

