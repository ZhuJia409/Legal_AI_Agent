import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.schemas.contract_background import ContractBackgroundResponse
from app.services.contract_evidence import segment_contract_markdown
from app.services.mineru_parser import MineruParseResult
from app.services.object_storage import ObjectStorageProtocol


@dataclass(frozen=True)
class ContractReviewSourceFile:
    filename: str
    content_type: str
    content: bytes


class ContractReviewSnapshotRepositoryProtocol(Protocol):
    async def create_task(self, *, task_id: str, title: str | None) -> None:
        """Create review task metadata."""

    async def save_document(self, **kwargs: object) -> None:
        """Save review document metadata."""

    async def save_paragraphs(self, *, task_id: str, paragraphs: list[dict[str, object]]) -> None:
        """Save immutable contract paragraphs."""

    async def save_context_snapshot(self, *, task_id: str, snapshot: dict[str, object]) -> None:
        """Save Phase 0 context snapshot."""


class ContractReviewAuditRepositoryProtocol(Protocol):
    async def record_event(
        self,
        *,
        task_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        """Save a review runtime event."""

    async def record_mineru_batch(self, *, task_id: str, payload: dict[str, object]) -> None:
        """Save raw MinerU batch metadata."""


class NoopContractReviewSnapshotRepository:
    async def create_task(self, *, task_id: str, title: str | None) -> None:
        return None

    async def save_document(self, **kwargs: object) -> None:
        return None

    async def save_paragraphs(self, *, task_id: str, paragraphs: list[dict[str, object]]) -> None:
        return None

    async def save_context_snapshot(self, *, task_id: str, snapshot: dict[str, object]) -> None:
        return None


class NoopContractReviewAuditRepository:
    async def record_event(
        self,
        *,
        task_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        return None

    async def record_mineru_batch(self, *, task_id: str, payload: dict[str, object]) -> None:
        return None


class ContractReviewPersistenceService:
    def __init__(
        self,
        *,
        object_storage: ObjectStorageProtocol,
        snapshot_repository: ContractReviewSnapshotRepositoryProtocol,
        audit_repository: ContractReviewAuditRepositoryProtocol,
    ) -> None:
        self.object_storage = object_storage
        self.snapshot_repository = snapshot_repository
        self.audit_repository = audit_repository

    async def persist_review(
        self,
        *,
        task_id: str,
        title: str | None,
        response: ContractBackgroundResponse,
        source_file: ContractReviewSourceFile | None = None,
        related_files: Sequence[ContractReviewSourceFile] = (),
        mineru_result: MineruParseResult | None = None,
        content: str | None = None,
        raw_model_output: dict[str, object] | None = None,
    ) -> None:
        await self.audit_repository.record_event(
            task_id=task_id,
            event_type="contract_review_persist_started",
            payload={"title": title},
        )
        await self.snapshot_repository.create_task(task_id=task_id, title=title)
        if raw_model_output is not None:
            await self.audit_repository.record_event(
                task_id=task_id,
                event_type="contract_review_llm_raw_output",
                payload=raw_model_output,
            )

        if source_file is not None:
            object_key = await self._store_source_file(task_id, source_file)
            await self._save_document_metadata(
                task_id=task_id,
                document_type="source_main",
                filename=source_file.filename,
                content_type=source_file.content_type,
                content=source_file.content,
                object_key=object_key,
                mineru_batch_id=mineru_result.batch_id if mineru_result else None,
            )

        for related_file in related_files:
            object_key = await self._store_related_file(task_id, related_file)
            await self._save_document_metadata(
                task_id=task_id,
                document_type="related_registered",
                filename=related_file.filename,
                content_type=related_file.content_type,
                content=related_file.content,
                object_key=object_key,
                mineru_batch_id=None,
            )

        markdown = content
        if mineru_result is not None:
            markdown = mineru_result.markdown
            await self._store_mineru_artifacts(task_id, mineru_result)

        if markdown:
            await self.snapshot_repository.save_paragraphs(
                task_id=task_id,
                paragraphs=_paragraph_payloads(markdown),
            )

        await self.snapshot_repository.save_context_snapshot(
            task_id=task_id,
            snapshot=_context_snapshot_payload(response),
        )
        await self.audit_repository.record_event(
            task_id=task_id,
            event_type="contract_review_persist_completed",
            payload={},
        )

    async def _store_source_file(
        self,
        task_id: str,
        source_file: ContractReviewSourceFile,
    ) -> str:
        key = f"contract-reviews/{task_id}/source/main/{_safe_object_name(source_file.filename)}"
        return await self.object_storage.put_bytes(
            key=key,
            content=source_file.content,
            content_type=source_file.content_type,
        )

    async def _store_related_file(
        self,
        task_id: str,
        related_file: ContractReviewSourceFile,
    ) -> str:
        safe_filename = _safe_object_name(related_file.filename)
        key = f"contract-reviews/{task_id}/source/related/{safe_filename}"
        return await self.object_storage.put_bytes(
            key=key,
            content=related_file.content,
            content_type=related_file.content_type,
        )

    async def _store_mineru_artifacts(
        self,
        task_id: str,
        mineru_result: MineruParseResult,
    ) -> None:
        zip_key = f"contract-reviews/{task_id}/mineru/{mineru_result.batch_id}/result.zip"
        markdown_key = f"contract-reviews/{task_id}/mineru/{mineru_result.batch_id}/full.md"
        await self.object_storage.put_bytes(
            key=zip_key,
            content=mineru_result.zip_bytes,
            content_type="application/zip",
        )
        await self._save_document_metadata(
            task_id=task_id,
            document_type="mineru_result_zip",
            filename="result.zip",
            content_type="application/zip",
            content=mineru_result.zip_bytes,
            object_key=zip_key,
            mineru_batch_id=mineru_result.batch_id,
        )
        markdown_bytes = mineru_result.markdown.encode("utf-8")
        await self.object_storage.put_bytes(
            key=markdown_key,
            content=markdown_bytes,
            content_type="text/markdown; charset=utf-8",
        )
        await self._save_document_metadata(
            task_id=task_id,
            document_type="mineru_full_markdown",
            filename="full.md",
            content_type="text/markdown; charset=utf-8",
            content=markdown_bytes,
            object_key=markdown_key,
            mineru_batch_id=mineru_result.batch_id,
        )
        await self.audit_repository.record_mineru_batch(
            task_id=task_id,
            payload={
                "batch_id": mineru_result.batch_id,
                "zip_object_key": zip_key,
                "markdown_object_key": markdown_key,
            },
        )

    async def _save_document_metadata(
        self,
        *,
        task_id: str,
        document_type: str,
        filename: str,
        content_type: str,
        content: bytes,
        object_key: str,
        mineru_batch_id: str | None,
    ) -> None:
        await self.snapshot_repository.save_document(
            task_id=task_id,
            document_type=document_type,
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            object_key=object_key,
            mineru_batch_id=mineru_batch_id,
        )


def _paragraph_payloads(markdown: str) -> list[dict[str, object]]:
    return [
        {
            "paragraph_id": segment.paragraph_id,
            "clause_path": segment.clause_path,
            "paragraph_index": segment.paragraph_index,
            "start_char": segment.start_char,
            "end_char": segment.end_char,
            "text": segment.text,
            "kind": segment.kind,
        }
        for segment in segment_contract_markdown(markdown)
    ]


def _context_snapshot_payload(response: ContractBackgroundResponse) -> dict[str, object]:
    return {
        "background_card": response.background_card.model_dump(mode="json"),
        "contract_category": response.contract_category,
        "related_documents": [
            document.model_dump(mode="json") for document in response.related_documents
        ],
        "pitfalls": [pitfall.model_dump(mode="json") for pitfall in response.pitfalls],
    }


def _safe_object_name(filename: str) -> str:
    safe_name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    safe_name = re.sub(r"[\r\n]+", "_", safe_name)
    return safe_name or "uploaded-contract"
