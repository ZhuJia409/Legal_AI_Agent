from datetime import UTC, datetime

import pytest

from app.services.case_analysis.document import GeneratedCaseDocument
from app.services.case_analysis.persistence import (
    CaseAnalysisDocumentReadError,
    CaseAnalysisPersistenceService,
    CaseAnalysisStoredDocumentService,
)
from tests.test_case_analysis_api import _case_response


class FakeStorage:
    def __init__(self, content: bytes = b"docx") -> None:
        self.content = content
        self.puts: list[dict[str, object]] = []

    async def put_bytes(self, **kwargs: object) -> str:
        self.puts.append(kwargs)
        return str(kwargs["key"])

    async def get_bytes(self, *, key: str) -> bytes:
        return self.content


class FakeRepository:
    def __init__(self) -> None:
        self.saved: list[dict[str, object]] = []
        self.record = None

    async def save(self, **values: object) -> None:
        self.saved.append(values)

    async def get(self, analysis_id: str):  # noqa: ANN201
        return self.record


@pytest.mark.asyncio
async def test_case_persistence_stores_pdf_and_snapshot_with_public_metadata() -> None:
    content = b"%PDF-case-content"
    generated = GeneratedCaseDocument(
        filename="草稿.pdf",
        content_type="application/pdf",
        content=content,
        sha256=__import__("hashlib").sha256(content).hexdigest(),
        generated_at=datetime(2026, 7, 14, tzinfo=UTC),
    )
    response = _case_response()
    storage = FakeStorage()
    repository = FakeRepository()

    await CaseAnalysisPersistenceService(repository=repository, object_storage=storage).persist(
        title="测试案件", response=response, document=generated
    )

    assert response.draft_document is not None
    assert response.draft_document.download_path.endswith("/analysis-123/document")
    assert storage.puts[0]["key"] == "case-analyses/analysis-123/documents/草稿.pdf"
    assert repository.saved[0]["response_payload"]["draft_document"]["format"] == "pdf"  # type: ignore[index]


@pytest.mark.asyncio
async def test_case_document_service_rejects_corrupt_bytes() -> None:
    from app.repositories.case_analysis import CaseAnalysisRecord

    repository = FakeRepository()
    repository.record = CaseAnalysisRecord(
        analysis_id="id",
        title=None,
        status="complete",
        risk_level="medium",
        response_payload={},
        document_filename="草稿.docx",
        document_content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        document_size_bytes=4,
        document_sha256="a" * 64,
        document_object_key="key",
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        updated_at=datetime(2026, 7, 14, tzinfo=UTC),
    )

    with pytest.raises(CaseAnalysisDocumentReadError):
        await CaseAnalysisStoredDocumentService(
            repository=repository, object_storage=FakeStorage(b"bad!")
        ).get_document("id")
