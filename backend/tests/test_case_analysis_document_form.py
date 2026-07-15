from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import case_analysis as schemas


def _form_payload() -> dict[str, object]:
    return {
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
                "text": "双方未办理结婚登记。",
                "paragraph_ids": ["p0001"],
            }
        ],
        "core_positions_or_requests": ["款项性质和返还范围需结合给付目的判断。"],
        "recommended_actions": ["补充银行流水"],
        "missing_information": ["代理立场"],
        "lawyer_review_items": ["核对管辖和请求范围"],
    }


def test_document_form_schema_enforces_limits_and_unique_strategy_modes() -> None:
    form_type = getattr(schemas, "AgentCaseDocumentFormDraft", None)
    assert form_type is not None, "document form schema is not implemented"

    valid = form_type.model_validate(_form_payload())
    assert valid.strategies[0].mode == "balanced"

    too_many_actions = _form_payload()
    too_many_actions["strategies"][0]["actions"] = ["动作"] * 4  # type: ignore[index]
    with pytest.raises(ValidationError):
        form_type.model_validate(too_many_actions)

    duplicate_modes = _form_payload()
    duplicate_modes["strategies"] = [
        duplicate_modes["strategies"][0],  # type: ignore[index]
        duplicate_modes["strategies"][0],  # type: ignore[index]
    ]
    with pytest.raises(ValidationError):
        form_type.model_validate(duplicate_modes)

    overly_long_item = _form_payload()
    overly_long_item["recommended_actions"] = ["动" * 201]
    with pytest.raises(ValidationError):
        form_type.model_validate(overly_long_item)


def test_document_form_facts_require_material_paragraph_ids() -> None:
    form_type = getattr(schemas, "AgentCaseDocumentFormDraft", None)
    assert form_type is not None, "document form schema is not implemented"
    payload = _form_payload()
    payload["key_facts"][0]["paragraph_ids"] = []  # type: ignore[index]

    with pytest.raises(ValidationError):
        form_type.model_validate(payload)
