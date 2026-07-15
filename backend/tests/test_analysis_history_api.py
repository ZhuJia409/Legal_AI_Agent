from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.v1.analysis import get_contract_review_history_service
from app.api.v1.case_analyses import (
    get_case_analysis_history_service,
    get_case_stored_document_service,
)
from app.main import app
from app.schemas.case_analysis import CaseAnalysisHistoryResponse
from app.schemas.contract_review import ContractReviewHistoryResponse
from app.services.analysis_history import HistoryNotFoundError
from app.services.case_analysis_persistence import CaseAnalysisDocumentDownload
from tests.test_case_analysis_api import _case_response
from tests.test_contract_review_report_api import _downloadable_document, _report_response


class FakeContractHistory:
    async def list_history(self) -> ContractReviewHistoryResponse:
        return ContractReviewHistoryResponse.model_validate(
            {
                "items": [
                    {
                        "task_id": "123e4567-e89b-12d3-a456-426614174000",
                        "title": "采购合同",
                        "status": "complete",
                        "risk_level": "medium",
                        "created_at": datetime(2026, 7, 14, tzinfo=UTC),
                    }
                ]
            }
        )

    async def get_report(self, task_id: str):  # noqa: ANN201
        return _report_response(task_id, "neutral")


class FakeCaseHistory:
    def __init__(self, missing: bool = False) -> None:
        self.missing = missing

    async def list_history(self) -> CaseAnalysisHistoryResponse:
        return CaseAnalysisHistoryResponse.model_validate(
            {
                "items": [
                    {
                        "analysis_id": "123e4567-e89b-12d3-a456-426614174001",
                        "title": "婚约财产纠纷",
                        "status": "partial",
                        "risk_level": "high",
                        "created_at": datetime(2026, 7, 14, tzinfo=UTC),
                    }
                ]
            }
        )

    async def get_analysis(self, analysis_id: str):  # noqa: ANN201
        if self.missing:
            raise HistoryNotFoundError("missing")
        return _case_response()


class FakeStoredCaseDocument:
    def __init__(self, *, pdf: bool = False) -> None:
        self.pdf = pdf

    async def get_document(self, analysis_id: str) -> CaseAnalysisDocumentDownload:
        from app.repositories.case_analysis import CaseAnalysisRecord

        report = _downloadable_document()
        record = CaseAnalysisRecord(
            analysis_id=analysis_id,
            title="案件",
            status="complete",
            risk_level="medium",
            response_payload={},
            document_filename="案件草稿.pdf" if self.pdf else "案件草稿.docx",
            document_content_type=(
                "application/pdf"
                if self.pdf
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            document_size_bytes=len(report.content),
            document_sha256=report.metadata.sha256,
            document_object_key="key",
            created_at=datetime(2026, 7, 14, tzinfo=UTC),
            updated_at=datetime(2026, 7, 14, tzinfo=UTC),
        )
        return CaseAnalysisDocumentDownload(record=record, content=report.content)


def test_contract_and_case_history_endpoints_return_saved_results() -> None:
    app.dependency_overrides.clear()
    app.dependency_overrides[get_contract_review_history_service] = lambda: FakeContractHistory()
    app.dependency_overrides[get_case_analysis_history_service] = lambda: FakeCaseHistory()
    client = TestClient(app)

    contract_list = client.get("/api/v1/contract-review-reports")
    contract_detail = client.get(
        "/api/v1/contract-review-reports/123e4567-e89b-12d3-a456-426614174000"
    )
    case_list = client.get("/api/v1/case-analyses")
    case_detail = client.get(
        "/api/v1/case-analyses/123e4567-e89b-12d3-a456-426614174001"
    )

    assert contract_list.status_code == contract_detail.status_code == 200
    assert contract_list.json()["items"][0]["title"] == "采购合同"
    assert contract_detail.json()["module"] == "contract_review_report"
    assert case_list.status_code == case_detail.status_code == 200
    assert case_list.json()["items"][0]["risk_level"] == "high"
    assert case_detail.json()["module"] == "case_analysis"
    app.dependency_overrides.clear()


def test_case_history_missing_and_docx_download_are_controlled() -> None:
    app.dependency_overrides.clear()


def test_case_pdf_download_uses_dynamic_content_type_and_filename() -> None:
    app.dependency_overrides.clear()
    app.dependency_overrides[get_case_stored_document_service] = lambda: (
        FakeStoredCaseDocument(pdf=True)
    )
    client = TestClient(app)
    task_id = "123e4567-e89b-12d3-a456-426614174001"

    document = client.get(f"/api/v1/case-analyses/{task_id}/document")

    assert document.status_code == 200
    assert document.headers["content-type"].startswith("application/pdf")
    assert 'filename="case-analysis-draft.pdf"' in document.headers[
        "content-disposition"
    ]
    assert "filename*=UTF-8''" in document.headers["content-disposition"]
    app.dependency_overrides.clear()
    app.dependency_overrides[get_case_analysis_history_service] = lambda: FakeCaseHistory(True)
    app.dependency_overrides[get_case_stored_document_service] = lambda: FakeStoredCaseDocument()
    client = TestClient(app)
    task_id = "123e4567-e89b-12d3-a456-426614174001"

    missing = client.get(f"/api/v1/case-analyses/{task_id}")
    document = client.get(f"/api/v1/case-analyses/{task_id}/document")

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "history_not_found"
    assert document.status_code == 200
    assert document.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "filename*=UTF-8''" in document.headers["content-disposition"]
    app.dependency_overrides.clear()
