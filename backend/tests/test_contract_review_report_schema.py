import pytest
from pydantic import ValidationError

from app.schemas.contract_background import SourceRef
from app.schemas.contract_review import (
    ContractTypeCode,
    ContractTypeSelection,
    ContractTypeSelectionDraft,
    ReviewFinding,
    ReviewModuleResult,
)


def test_contract_type_selection_draft_rejects_more_than_three_types() -> None:
    with pytest.raises(ValidationError):
        ContractTypeSelectionDraft(
            summary="混合合同",
            contract_types=[
                ContractTypeSelection(
                    code=code,
                    label=code.value,
                    rule_pack=f"references/{code.value}.md",
                    is_primary=index == 0,
                    reason="合同文本包含对应交易安排。",
                    source_refs=[],
                )
                for index, code in enumerate(
                    (
                        ContractTypeCode.SALE,
                        ContractTypeCode.LEASE,
                        ContractTypeCode.TECHNOLOGY,
                        ContractTypeCode.NDA,
                    )
                )
            ],
            findings=[],
            missing_evidence=[],
        )


def test_review_module_result_keeps_resolved_source_references() -> None:
    finding = ReviewFinding(
        finding_id="party_qualification-001",
        module="party_qualification",
        risk_level="high",
        contract_location="第一条",
        issue="签约代表授权文件缺失",
        basis="合同未附授权委托书。",
        impact="可能产生无权代理争议。",
        suggestion="签署前补充有效授权委托书。",
        negotiation_strategy="将授权文件列为合同生效条件。",
        source_refs=[
            SourceRef(
                paragraph_id="p0001",
                clause_path="第一条",
                quote="甲方代表签署本合同。",
            )
        ],
        requires_human_review=True,
    )

    result = ReviewModuleResult(
        module="party_qualification",
        status="succeeded",
        summary="发现一项授权风险。",
        findings=[finding],
        missing_evidence=["授权委托书"],
    )

    assert result.findings[0].source_refs[0].paragraph_id == "p0001"
    assert result.findings[0].requires_human_review is True
