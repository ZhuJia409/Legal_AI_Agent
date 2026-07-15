from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.case_analysis import AgentFindingDraft, CaseRiskItem
from app.services.case_analysis.evidence import (
    UnknownCaseSourceError,
    resolve_source_refs,
    segment_case_material,
)


def test_agent_draft_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AgentFindingDraft.model_validate(
            {
                "title": "彩礼性质",
                "detail": "需要结合给付目的判断。",
                "paragraph_ids": ["p0001"],
                "unexpected": "forbidden",
            }
        )


def test_risk_item_rejects_unknown_enum_value() -> None:
    with pytest.raises(ValidationError):
        CaseRiskItem.model_validate(
            {
                "dimension": "internal",
                "title": "证据风险",
                "detail": "缺少转账凭证。",
                "risk_level": "critical",
                "mitigation": "补充银行流水。",
                "source_refs": [],
            }
        )


def test_segment_case_material_assigns_stable_paragraph_ids() -> None:
    segments = segment_case_material("# 案件材料\n\n第一段事实\n换行继续\n\n第二段事实")

    assert [(item.paragraph_id, item.text) for item in segments] == [
        ("p0001", "# 案件材料"),
        ("p0002", "第一段事实\n换行继续"),
        ("p0003", "第二段事实"),
    ]


def test_resolve_source_refs_uses_server_owned_quotes() -> None:
    segments = segment_case_material("第一段事实\n\n第二段事实")

    refs = resolve_source_refs(["p0002"], segments)

    assert len(refs) == 1
    assert refs[0].paragraph_id == "p0002"
    assert refs[0].quote == "第二段事实"


def test_resolve_source_refs_rejects_unknown_paragraph_id() -> None:
    segments = segment_case_material("唯一事实")

    with pytest.raises(UnknownCaseSourceError, match="p9999"):
        resolve_source_refs(["p9999"], segments)
