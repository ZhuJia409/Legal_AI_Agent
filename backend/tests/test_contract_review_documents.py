import hashlib
from datetime import UTC, datetime

import pytest

from app.repositories.contract_review import ReviewDocumentRecord
from app.services.contract_review_documents import (
    ContractReviewDocumentService,
    ReportDocumentNotFoundError,
    ReportDocumentReadError,
)
from app.services.object_storage import MinioObjectStorage, ObjectStorageReadError


class FakeDocumentRepository:
    def __init__(self, record: ReviewDocumentRecord | None) -> None:
        self.record = record
        self.calls: list[tuple[str, str]] = []

    async def get_latest_document(
        self,
        *,
        task_id: str,
        document_type: str,
    ) -> ReviewDocumentRecord | None:
        self.calls.append((task_id, document_type))
        return self.record


class FakeReadableObjectStorage:
    def __init__(self, content: bytes | Exception) -> None:
        self.content = content
        self.keys: list[str] = []

    async def get_bytes(self, *, key: str) -> bytes:
        self.keys.append(key)
        if isinstance(self.content, Exception):
            raise self.content
        return self.content


def _record(content: bytes) -> ReviewDocumentRecord:
    return ReviewDocumentRecord(
        task_id="123e4567-e89b-12d3-a456-426614174000",
        document_type="contract_review_report_pdf",
        filename="采购合同_合同审查报告.pdf",
        content_type="application/pdf",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        object_key="contract-reviews/task/reports/report.pdf",
        created_at=datetime(2026, 7, 13, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_document_service_reads_and_verifies_pdf() -> None:
    content = b"%PDF-report"
    repository = FakeDocumentRepository(_record(content))
    storage = FakeReadableObjectStorage(content)
    service = ContractReviewDocumentService(repository=repository, object_storage=storage)

    document = await service.get_report_pdf("123e4567-e89b-12d3-a456-426614174000")

    assert document.content == content
    assert document.metadata.filename == "采购合同_合同审查报告.pdf"
    assert repository.calls == [
        ("123e4567-e89b-12d3-a456-426614174000", "contract_review_report_pdf")
    ]
    assert storage.keys == ["contract-reviews/task/reports/report.pdf"]


@pytest.mark.asyncio
async def test_document_service_reports_missing_metadata() -> None:
    service = ContractReviewDocumentService(
        repository=FakeDocumentRepository(None),
        object_storage=FakeReadableObjectStorage(b"unused"),
    )

    with pytest.raises(ReportDocumentNotFoundError):
        await service.get_report_pdf("123e4567-e89b-12d3-a456-426614174000")


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"short", b"%PDF-tampered"])
async def test_document_service_rejects_size_or_digest_mismatch(content: bytes) -> None:
    expected = b"%PDF-report"
    service = ContractReviewDocumentService(
        repository=FakeDocumentRepository(_record(expected)),
        object_storage=FakeReadableObjectStorage(content),
    )

    with pytest.raises(ReportDocumentReadError):
        await service.get_report_pdf("123e4567-e89b-12d3-a456-426614174000")


@pytest.mark.asyncio
async def test_document_service_converts_object_storage_failure() -> None:
    content = b"%PDF-report"
    service = ContractReviewDocumentService(
        repository=FakeDocumentRepository(_record(content)),
        object_storage=FakeReadableObjectStorage(ObjectStorageReadError("unavailable")),
    )

    with pytest.raises(ReportDocumentReadError):
        await service.get_report_pdf("123e4567-e89b-12d3-a456-426614174000")


class FakeObjectResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False
        self.released = False

    def read(self) -> bytes:
        return self.content

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class FakeMinioClient:
    def __init__(self, result: FakeObjectResponse | Exception) -> None:
        self.result = result

    def get_object(self, bucket: str, key: str) -> FakeObjectResponse:
        assert bucket == "reports"
        assert key == "report.pdf"
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.asyncio
async def test_minio_get_bytes_closes_response() -> None:
    response = FakeObjectResponse(b"%PDF-report")
    storage = MinioObjectStorage(
        endpoint="127.0.0.1:9000",
        access_key="test",
        secret_key="test",
        bucket="reports",
    )
    storage.client = FakeMinioClient(response)  # type: ignore[assignment]

    assert await storage.get_bytes(key="report.pdf") == b"%PDF-report"
    assert response.closed is True
    assert response.released is True


@pytest.mark.asyncio
async def test_minio_get_bytes_hides_backend_error() -> None:
    storage = MinioObjectStorage(
        endpoint="127.0.0.1:9000",
        access_key="test",
        secret_key="test",
        bucket="reports",
    )
    storage.client = FakeMinioClient(RuntimeError("endpoint secret"))  # type: ignore[assignment]

    with pytest.raises(ObjectStorageReadError, match="对象存储读取失败") as captured:
        await storage.get_bytes(key="report.pdf")

    assert "endpoint secret" not in str(captured.value)
