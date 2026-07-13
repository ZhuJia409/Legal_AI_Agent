from datetime import UTC, datetime

import pytest

from app.db.models import ReviewDocument
from app.repositories.contract_review import SqlAlchemyContractReviewSnapshotRepository


class FakeScalarResult:
    def __init__(self, document: ReviewDocument | None) -> None:
        self.document = document

    def scalar_one_or_none(self) -> ReviewDocument | None:
        return self.document


class FakeSession:
    def __init__(self, document: ReviewDocument | None) -> None:
        self.document = document
        self.statements: list[object] = []

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, statement: object) -> FakeScalarResult:
        self.statements.append(statement)
        return FakeScalarResult(self.document)


class FakeSessionFactory:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __call__(self) -> FakeSession:
        return self.session


@pytest.mark.asyncio
async def test_repository_returns_latest_document_record() -> None:
    created_at = datetime(2026, 7, 13, tzinfo=UTC)
    document = ReviewDocument(
        task_id="task-1",
        document_type="contract_review_report_pdf",
        filename="报告.pdf",
        content_type="application/pdf",
        size_bytes=12,
        sha256="a" * 64,
        object_key="contract-reviews/task-1/reports/report.pdf",
        mineru_batch_id=None,
        created_at=created_at,
    )
    document.id = 3
    session = FakeSession(document)
    repository = SqlAlchemyContractReviewSnapshotRepository(
        FakeSessionFactory(session)  # type: ignore[arg-type]
    )

    record = await repository.get_latest_document(
        task_id="task-1",
        document_type="contract_review_report_pdf",
    )

    assert record is not None
    assert record.filename == "报告.pdf"
    assert record.created_at == created_at
    statement = str(session.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "review_document.task_id = 'task-1'" in statement
    assert "review_document.document_type = 'contract_review_report_pdf'" in statement
    assert "ORDER BY review_document.created_at DESC, review_document.id DESC" in statement


@pytest.mark.asyncio
async def test_repository_returns_none_when_document_is_missing() -> None:
    repository = SqlAlchemyContractReviewSnapshotRepository(
        FakeSessionFactory(FakeSession(None))  # type: ignore[arg-type]
    )

    assert (
        await repository.get_latest_document(
            task_id="task-1",
            document_type="contract_review_report_pdf",
        )
        is None
    )
