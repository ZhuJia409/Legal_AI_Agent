from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import anyio
from pymongo import MongoClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import ContextSnapshot, ContractParagraph, ReviewDocument, ReviewTask


@dataclass(frozen=True, slots=True)
class ReviewDocumentRecord:
    """跨越 repository 边界的只读文档元数据，避免向服务层暴露 ORM 会话对象。"""

    task_id: str
    document_type: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    object_key: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ContractReviewHistoryRecord:
    task_id: str
    title: str | None
    status: str
    overall_risk_level: str
    created_at: datetime


class SqlAlchemyContractReviewSnapshotRepository:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.session_factory = session_factory

    async def create_task(self, *, task_id: str, title: str | None) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                await session.merge(
                    ReviewTask(
                        task_id=task_id,
                        title=title,
                        status="succeeded",
                    )
                )

    async def save_document(self, **kwargs: object) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                session.add(
                    ReviewDocument(
                        task_id=str(kwargs["task_id"]),
                        document_type=str(kwargs["document_type"]),
                        filename=str(kwargs["filename"]),
                        content_type=str(kwargs["content_type"]),
                        size_bytes=int(kwargs["size_bytes"]),
                        sha256=str(kwargs["sha256"]),
                        object_key=str(kwargs["object_key"]),
                        mineru_batch_id=(
                            str(kwargs["mineru_batch_id"])
                            if kwargs.get("mineru_batch_id") is not None
                            else None
                        ),
                    )
                )

    async def get_latest_document(
        self,
        *,
        task_id: str,
        document_type: str,
    ) -> ReviewDocumentRecord | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(ReviewDocument)
                .where(
                    ReviewDocument.task_id == task_id,
                    ReviewDocument.document_type == document_type,
                )
                # 当前每个任务只发布一份报告；倒序仍兼容未来重新生成。
                .order_by(ReviewDocument.created_at.desc(), ReviewDocument.id.desc())
                .limit(1)
            )
            document = result.scalar_one_or_none()
            if document is None:
                return None
            return ReviewDocumentRecord(
                task_id=document.task_id,
                document_type=document.document_type,
                filename=document.filename,
                content_type=document.content_type,
                size_bytes=document.size_bytes,
                sha256=document.sha256,
                object_key=document.object_key,
                created_at=document.created_at,
            )

    async def list_report_history(
        self, *, limit: int = 50
    ) -> list[ContractReviewHistoryRecord]:
        safe_limit = max(1, min(limit, 50))
        async with self.session_factory() as session:
            result = await session.execute(
                select(ReviewTask, ContextSnapshot)
                .join(ContextSnapshot, ContextSnapshot.task_id == ReviewTask.task_id)
                .join(ReviewDocument, ReviewDocument.task_id == ReviewTask.task_id)
                .where(ReviewDocument.document_type == "contract_review_report_pdf")
                .order_by(ReviewTask.created_at.desc())
                .limit(safe_limit)
            )
            records: list[ContractReviewHistoryRecord] = []
            seen: set[str] = set()
            for task, snapshot in result.all():
                if task.task_id in seen:
                    continue
                full_report = snapshot.snapshot_payload.get("full_report")
                if not isinstance(full_report, dict):
                    continue
                report = full_report.get("report")
                risk = report.get("overall_risk_level") if isinstance(report, dict) else "unknown"
                records.append(
                    ContractReviewHistoryRecord(
                        task_id=task.task_id,
                        title=task.title,
                        status=str(full_report.get("status") or task.status),
                        overall_risk_level=str(risk or "unknown"),
                        created_at=task.created_at,
                    )
                )
                seen.add(task.task_id)
            return records[:safe_limit]

    async def get_report_snapshot(self, task_id: str) -> object | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(ContextSnapshot.snapshot_payload).where(ContextSnapshot.task_id == task_id)
            )
            snapshot = result.scalar_one_or_none()
            if not isinstance(snapshot, dict):
                return None
            return snapshot.get("full_report")

    async def save_paragraphs(self, *, task_id: str, paragraphs: list[dict[str, object]]) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                await session.execute(
                    delete(ContractParagraph).where(ContractParagraph.task_id == task_id)
                )
                session.add_all(
                    [
                        ContractParagraph(
                            task_id=task_id,
                            paragraph_id=str(paragraph["paragraph_id"]),
                            clause_path=(
                                str(paragraph["clause_path"])
                                if paragraph.get("clause_path") is not None
                                else None
                            ),
                            paragraph_index=int(paragraph["paragraph_index"]),
                            start_char=int(paragraph["start_char"]),
                            end_char=int(paragraph["end_char"]),
                            text=str(paragraph["text"]),
                            kind=str(paragraph["kind"]),
                        )
                        for paragraph in paragraphs
                    ]
                )

    async def save_context_snapshot(self, *, task_id: str, snapshot: dict[str, object]) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                await session.merge(
                    ContextSnapshot(
                        task_id=task_id,
                        contract_category=str(snapshot["contract_category"]),
                        background_card=_dict(snapshot["background_card"]),
                        related_documents=_list_of_dicts(snapshot["related_documents"]),
                        pitfalls=_list_of_dicts(snapshot["pitfalls"]),
                        snapshot_payload=snapshot,
                    )
                )
                task = await session.get(ReviewTask, task_id)
                if task is not None:
                    # 完整审查允许保存 partial；背景审查未提供状态时仍视为成功。
                    task.status = str(snapshot.get("status") or "succeeded")


class PymongoContractReviewAuditRepository:
    def __init__(self, mongodb_url: str) -> None:
        self.client: MongoClient[dict[str, Any]] = MongoClient(mongodb_url)
        self.database = self.client.get_default_database()
        self.events = self.database["contract_review_events"]
        self.mineru_batches = self.database["contract_review_mineru_batches"]

    async def record_event(
        self,
        *,
        task_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        document = {
            "task_id": task_id,
            "event_type": event_type,
            "payload": payload,
            "created_at": datetime.now(UTC),
        }
        await anyio.to_thread.run_sync(self.events.insert_one, document)

    async def record_mineru_batch(self, *, task_id: str, payload: dict[str, object]) -> None:
        document = {
            "task_id": task_id,
            "payload": payload,
            "created_at": datetime.now(UTC),
        }
        await anyio.to_thread.run_sync(self.mineru_batches.insert_one, document)


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
