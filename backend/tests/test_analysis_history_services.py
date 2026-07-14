from datetime import UTC, datetime

import pytest

from app.repositories.case_analysis import CaseAnalysisRecord
from app.repositories.contract_review import ContractReviewHistoryRecord
from app.services.analysis_history import (
    CaseAnalysisHistoryService,
    ContractReviewHistoryService,
    HistoryNotFoundError,
    HistorySnapshotError,
)


class FakeContractRepository:
    def __init__(self, records: list[ContractReviewHistoryRecord], snapshot: object) -> None:
        self.records = records
        self.snapshot = snapshot

    async def list_report_history(self, *, limit: int) -> list[ContractReviewHistoryRecord]:
        assert limit == 50
        return self.records

    async def get_report_snapshot(self, task_id: str) -> object:
        return self.snapshot


class FakeCaseRepository:
    def __init__(
        self,
        records: list[CaseAnalysisRecord],
        record: CaseAnalysisRecord | None,
    ) -> None:
        self.records = records
        self.record = record

    async def list_history(self, *, limit: int) -> list[CaseAnalysisRecord]:
        assert limit == 50
        return self.records

    async def get(self, analysis_id: str) -> CaseAnalysisRecord | None:
        return self.record


def _case_payload() -> dict[str, object]:
    from tests.test_case_analysis_api import _case_response

    return _case_response().model_dump(mode="json")


@pytest.mark.asyncio
async def test_history_services_return_summaries_and_restore_strict_snapshots() -> None:
    created_at = datetime(2026, 7, 14, tzinfo=UTC)
    contract_payload = {
        "module": "contract_review_report",
        "task_id": "123e4567-e89b-12d3-a456-426614174000",
        "status": "complete",
        "review_perspective": "neutral",
        "background": {
            "module": "contract_background",
            "summary": "背景",
            "background_card": {},
            "contract_category": "other_unknown",
            "related_documents": [],
            "missing_questions": [],
            "pitfalls": [],
            "disclaimer": "需复核",
        },
        "contract_types": [],
        "modules": [],
        "report": {
            "executive_summary": "审查摘要",
            "overall_risk_level": "medium",
            "signing_recommendation": "conditional",
            "preconditions": [],
            "findings": [],
            "limitations": [],
            "failed_modules": [],
        },
        "disclaimer": "需律师复核",
        "report_document": None,
    }
    contract_record = ContractReviewHistoryRecord(
        task_id="123e4567-e89b-12d3-a456-426614174000",
        title="采购合同",
        status="succeeded",
        overall_risk_level="medium",
        created_at=created_at,
    )
    contract_service = ContractReviewHistoryService(
        FakeContractRepository([contract_record], contract_payload)
    )
    case_record = CaseAnalysisRecord(
        analysis_id="123e4567-e89b-12d3-a456-426614174001",
        title="婚约财产纠纷",
        status="partial",
        risk_level="high",
        response_payload=_case_payload(),
        document_filename="草稿.docx",
        document_content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        document_size_bytes=12,
        document_sha256="a" * 64,
        document_object_key="case-analyses/id/document.docx",
        created_at=created_at,
        updated_at=created_at,
    )
    case_service = CaseAnalysisHistoryService(FakeCaseRepository([case_record], case_record))

    assert (await contract_service.list_history()).items[0].title == "采购合同"
    restored_contract = await contract_service.get_report(contract_record.task_id)
    assert restored_contract.task_id == contract_record.task_id
    assert (await case_service.list_history()).items[0].risk_level == "high"
    assert (await case_service.get_analysis(case_record.analysis_id)).analysis_id == "analysis-123"


@pytest.mark.asyncio
async def test_history_services_reject_missing_and_corrupt_snapshots() -> None:
    missing = CaseAnalysisHistoryService(FakeCaseRepository([], None))
    with pytest.raises(HistoryNotFoundError):
        await missing.get_analysis("123e4567-e89b-12d3-a456-426614174001")

    corrupt_contract = ContractReviewHistoryService(FakeContractRepository([], {"bad": True}))
    with pytest.raises(HistorySnapshotError):
        await corrupt_contract.get_report("123e4567-e89b-12d3-a456-426614174000")
