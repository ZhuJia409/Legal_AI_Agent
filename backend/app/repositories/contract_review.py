from datetime import UTC, datetime
from typing import Any

import anyio
from pymongo import MongoClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import ContextSnapshot, ContractParagraph, ReviewDocument, ReviewTask


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
                    task.status = "succeeded"


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
