import pytest
from pydantic import ValidationError

import app.schemas.contract_review as contract_review_schema


def _form_model():
    model = getattr(contract_review_schema, "ContractPdfDocumentForm", None)
    assert model is not None, "PDF 文书表单模型尚未实现"
    return model


def _valid_payload() -> dict[str, object]:
    return {
        "executive_conclusion": "合同存在主体授权和责任限制风险，建议修改后签署。",
        "priority_findings": [
            {
                "finding_id": "party_qualification-001",
                "display_title": "签约代表授权文件缺失",
                "risk_description": "合同仅列明代表姓名，未提供有效授权文件。",
                "legal_consequence": "可能产生代理权限及合同效力争议。",
                "revision_advice": "补充授权委托书并核验签署权限。",
                "negotiation_strategy": "将授权文件作为合同生效前提。",
            }
        ],
        "signing_preconditions": ["完成主体资格核验"],
        "pending_confirmations": ["确认乙方营业执照信息"],
        "lawyer_review_items": ["复核责任限制条款的有效性"],
    }


def test_contract_pdf_form_accepts_concise_strict_payload() -> None:
    form = _form_model().model_validate(_valid_payload())

    assert form.priority_findings[0].finding_id == "party_qualification-001"
    assert form.executive_conclusion.startswith("合同存在")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("executive_conclusion",), "结" * 301),
        (("priority_findings",), [_valid_payload()["priority_findings"][0]] * 9),  # type: ignore[index]
        (("signing_preconditions",), [f"前提 {index}" for index in range(6)]),
        (("pending_confirmations",), [f"待确认 {index}" for index in range(6)]),
        (("lawyer_review_items",), [f"复核 {index}" for index in range(6)]),
    ],
)
def test_contract_pdf_form_rejects_overlong_or_excess_items(
    path: tuple[str, ...],
    value: object,
) -> None:
    payload = _valid_payload()
    payload[path[0]] = value

    with pytest.raises(ValidationError):
        _form_model().model_validate(payload)


def test_contract_pdf_form_rejects_extra_fields_and_duplicate_finding_ids() -> None:
    extra_payload = _valid_payload() | {"latex_source": r"\input{secret}"}
    with pytest.raises(ValidationError):
        _form_model().model_validate(extra_payload)

    duplicate_payload = _valid_payload()
    first = duplicate_payload["priority_findings"][0]  # type: ignore[index]
    duplicate_payload["priority_findings"] = [first, dict(first)]  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="finding_id"):
        _form_model().model_validate(duplicate_payload)
