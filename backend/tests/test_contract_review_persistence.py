import hashlib
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.schemas.contract_background import (
    BackgroundCard,
    ContractBackgroundResponse,
    RelatedDocument,
    ReviewPitfall,
)
from app.schemas.contract_review import (
    ContractReviewReport,
    ContractReviewReportResponse,
    ReviewModuleResult,
)
from app.services.contract_review_pdf import GeneratedReportPdf
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

    stored_keys = [call.key for call in object_storage.calls]
    assert stored_keys[0] == "contract-reviews/task-2/source/main/contract.docx"
    assert stored_keys[1].startswith("contract-reviews/task-2/source/related/")
    assert stored_keys[1].endswith("-meeting-minutes.pdf")
    related_document = snapshot_repository.documents[1]
    assert related_document["document_type"] == "related_registered"
    assert related_document["filename"] == "meeting-minutes.pdf"


@pytest.mark.asyncio
async def test_persistence_saves_full_report_and_related_mineru_artifacts() -> None:
    object_storage = FakeObjectStorage()
    snapshot_repository = FakeSnapshotRepository()
    audit_repository = FakeAuditRepository()
    service = ContractReviewPersistenceService(
        object_storage=object_storage,
        snapshot_repository=snapshot_repository,
        audit_repository=audit_repository,
    )
    related_file = ContractReviewSourceFile(
        filename="spec.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=b"spec-source",
    )
    related_result = MineruParseResult(
        batch_id="related-batch",
        zip_bytes=b"related-zip",
        markdown="技术规格\n\n设备应支持三年质保。",
    )
    modules = [
        ReviewModuleResult(module=module, status="succeeded", summary="完成")
        for module in (
            "party_qualification",
            "form_structure",
            "general_substantive",
            "related_document_comparison",
            "contract_type_special",
        )
    ]
    response = ContractReviewReportResponse(
        module="contract_review_report",
        task_id="task-full",
        status="partial",
        review_perspective="neutral",
        background=_response(),
        contract_types=[],
        modules=modules,
        report=ContractReviewReport(
            executive_summary="部分审查完成。",
            overall_risk_level="high",
            signing_recommendation="conditional",
        ),
        disclaimer="不可作为签署依据。",
    )
    generated_pdf = GeneratedReportPdf(
        filename="采购合同_合同审查报告_不完整_20260713_taskfull.pdf",
        content_type="application/pdf",
        content=b"%PDF-report",
        sha256=hashlib.sha256(b"%PDF-report").hexdigest(),
        generated_at=datetime(2026, 7, 13, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    await service.persist_review(
        task_id="task-full",
        title="采购合同",
        response=response,
        related_files=[related_file],
        related_mineru_results=[(related_file, related_result)],
        raw_model_outputs=[{"module": "report", "payload": {"ok": True}}],
        report_pdf=generated_pdf,
    )

    keys = [call.key for call in object_storage.calls]
    assert "contract-reviews/task-full/mineru/related/related-batch/result.zip" in keys
    assert (
        "contract-reviews/task-full/reports/"
        "采购合同_合同审查报告_不完整_20260713_taskfull.pdf"
    ) in keys
    report_document = next(
        document
        for document in snapshot_repository.documents
        if document["document_type"] == "contract_review_report_pdf"
    )
    assert report_document["sha256"] == generated_pdf.sha256
    snapshot = snapshot_repository.snapshots[0]["snapshot"]
    assert snapshot["status"] == "partial"
    assert snapshot["full_report"]["module"] == "contract_review_report"
    assert snapshot["full_report"]["report_document"]["filename"] == generated_pdf.filename
    assert response.report_document is not None
    assert response.report_document.download_path == (
        "/api/v1/contract-review-reports/task-full/document"
    )
    assert any(
        event["event_type"] == "contract_review_agent_raw_output"
        for event in audit_repository.events
    )


@pytest.mark.asyncio
async def test_persistence_maps_complete_report_to_succeeded_task_status() -> None:
    snapshot_repository = FakeSnapshotRepository()
    service = ContractReviewPersistenceService(
        object_storage=FakeObjectStorage(),
        snapshot_repository=snapshot_repository,
        audit_repository=FakeAuditRepository(),
    )
    response = ContractReviewReportResponse(
        module="contract_review_report",
        task_id="task-complete",
        status="complete",
        review_perspective="neutral",
        background=_response(),
        contract_types=[],
        modules=[],
        report=ContractReviewReport(
            executive_summary="审查完成。",
            overall_risk_level="medium",
            signing_recommendation="conditional",
        ),
        disclaimer="需由专业法律人士复核。",
    )

    await service.persist_review(
        task_id="task-complete",
        title="采购合同",
        response=response,
    )

    snapshot = snapshot_repository.snapshots[0]["snapshot"]
    assert snapshot["status"] == "succeeded"
    assert snapshot["full_report"]["status"] == "complete"


@pytest.mark.asyncio
async def test_persistence_uses_distinct_object_keys_for_same_named_related_files() -> None:
    object_storage = FakeObjectStorage()
    snapshot_repository = FakeSnapshotRepository()
    service = ContractReviewPersistenceService(
        object_storage=object_storage,
        snapshot_repository=snapshot_repository,
        audit_repository=FakeAuditRepository(),
    )

    await service.persist_review(
        task_id="task-duplicates",
        title="采购合同",
        response=_response(),
        related_files=[
            ContractReviewSourceFile(
                filename="附件.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"first",
            ),
            ContractReviewSourceFile(
                filename="附件.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"second",
            ),
        ],
    )

    related_keys = [
        call.key for call in object_storage.calls if "/source/related/" in call.key
    ]
    assert len(related_keys) == 2
    assert len(set(related_keys)) == 2
