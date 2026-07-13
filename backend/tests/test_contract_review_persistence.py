from dataclasses import dataclass

import pytest

from app.schemas.contract_background import (
    BackgroundCard,
    ContractBackgroundResponse,
    RelatedDocument,
    ReviewPitfall,
)
from app.services.contract_review_persistence import (
    ContractReviewPersistenceService,
    ContractReviewSourceFile,
)
from app.services.mineru_parser import MineruParseResult


@dataclass
class StoredCall:
    key: str
    content: bytes
    content_type: str


class FakeObjectStorage:
    def __init__(self) -> None:
        self.calls: list[StoredCall] = []

    async def put_bytes(self, *, key: str, content: bytes, content_type: str) -> str:
        self.calls.append(StoredCall(key=key, content=content, content_type=content_type))
        return key


class FakeSnapshotRepository:
    def __init__(self) -> None:
        self.tasks: list[dict[str, object]] = []
        self.documents: list[dict[str, object]] = []
        self.paragraphs: list[dict[str, object]] = []
        self.snapshots: list[dict[str, object]] = []

    async def create_task(self, *, task_id: str, title: str | None) -> None:
        self.tasks.append({"task_id": task_id, "title": title})

    async def save_document(self, **kwargs: object) -> None:
        self.documents.append(dict(kwargs))

    async def save_paragraphs(self, *, task_id: str, paragraphs: list[dict[str, object]]) -> None:
        self.paragraphs.extend({"task_id": task_id, **paragraph} for paragraph in paragraphs)

    async def save_context_snapshot(self, *, task_id: str, snapshot: dict[str, object]) -> None:
        self.snapshots.append({"task_id": task_id, "snapshot": snapshot})


class FakeAuditRepository:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.mineru_batches: list[dict[str, object]] = []

    async def record_event(
        self,
        *,
        task_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        self.events.append({"task_id": task_id, "event_type": event_type, "payload": payload})

    async def record_mineru_batch(self, *, task_id: str, payload: dict[str, object]) -> None:
        self.mineru_batches.append({"task_id": task_id, "payload": payload})


def _response() -> ContractBackgroundResponse:
    return ContractBackgroundResponse(
        module="contract_background",
        summary="summary",
        contract_category="commercial_transaction",
        background_card=BackgroundCard(commercial_purpose="采购办公IT设备。"),
        related_documents=[RelatedDocument(name="技术规格/SOW/需求文档", status="missing")],
        missing_questions=[],
        pitfalls=[
            ReviewPitfall(
                name="名实不符",
                risk="需核对标题和正文。",
                review_action="复核标题、标的和核心义务。",
            )
        ],
        disclaimer="review required",
    )


@pytest.mark.asyncio
async def test_persistence_saves_original_mineru_artifacts_paragraphs_and_snapshot() -> None:
    object_storage = FakeObjectStorage()
    snapshot_repository = FakeSnapshotRepository()
    audit_repository = FakeAuditRepository()
    service = ContractReviewPersistenceService(
        object_storage=object_storage,
        snapshot_repository=snapshot_repository,
        audit_repository=audit_repository,
    )
    markdown = "**采购合同**\n\n1.1 甲方向乙方采购办公IT设备。"
    mineru_result = MineruParseResult(
        batch_id="batch-1",
        zip_bytes=b"zip-bytes",
        markdown=markdown,
    )

    await service.persist_review(
        task_id="task-1",
        title="采购合同",
        source_file=ContractReviewSourceFile(
            filename="contract.docx",
            content_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            content=b"source-bytes",
        ),
        mineru_result=mineru_result,
        response=_response(),
    )

    assert [call.key for call in object_storage.calls] == [
        "contract-reviews/task-1/source/main/contract.docx",
        "contract-reviews/task-1/mineru/batch-1/result.zip",
        "contract-reviews/task-1/mineru/batch-1/full.md",
    ]
    assert object_storage.calls[2].content == markdown.encode("utf-8")
    assert snapshot_repository.tasks == [{"task_id": "task-1", "title": "采购合同"}]
    assert [document["object_key"] for document in snapshot_repository.documents] == [
        "contract-reviews/task-1/source/main/contract.docx",
        "contract-reviews/task-1/mineru/batch-1/result.zip",
        "contract-reviews/task-1/mineru/batch-1/full.md",
    ]
    assert [paragraph["paragraph_id"] for paragraph in snapshot_repository.paragraphs] == [
        "p0001",
        "p0002",
    ]
    snapshot = snapshot_repository.snapshots[0]["snapshot"]
    assert snapshot["contract_category"] == "commercial_transaction"
    assert snapshot["related_documents"] == [
        {"name": "技术规格/SOW/需求文档", "status": "missing"}
    ]
    assert audit_repository.mineru_batches[0]["payload"]["batch_id"] == "batch-1"


@pytest.mark.asyncio
async def test_persistence_saves_related_files_as_registered_documents() -> None:
    object_storage = FakeObjectStorage()
    snapshot_repository = FakeSnapshotRepository()
    audit_repository = FakeAuditRepository()
    service = ContractReviewPersistenceService(
        object_storage=object_storage,
        snapshot_repository=snapshot_repository,
        audit_repository=audit_repository,
    )

    await service.persist_review(
        task_id="task-2",
        title="采购合同",
        source_file=ContractReviewSourceFile(
            filename="contract.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            content=b"source-bytes",
        ),
        related_files=[
            ContractReviewSourceFile(
                filename="meeting-minutes.pdf",
                content_type="application/pdf",
                content=b"related-bytes",
            )
        ],
        response=_response(),
        content="采购合同\n\n合同正文。",
    )

    assert [call.key for call in object_storage.calls] == [
        "contract-reviews/task-2/source/main/contract.docx",
        "contract-reviews/task-2/source/related/meeting-minutes.pdf",
    ]
    related_document = snapshot_repository.documents[1]
    assert related_document["document_type"] == "related_registered"
    assert related_document["filename"] == "meeting-minutes.pdf"
