import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.schemas.contract_background import ContractBackgroundResponse
from app.schemas.contract_review import ContractReviewReportResponse
from app.services.contract_evidence import segment_contract_markdown
from app.services.contract_review_pdf import GeneratedReportPdf
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
        """保存合同背景审查上下文快照。"""


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
        response: ContractBackgroundResponse | ContractReviewReportResponse,
        source_file: ContractReviewSourceFile | None = None,
        related_files: Sequence[ContractReviewSourceFile] = (),
        mineru_result: MineruParseResult | None = None,
        content: str | None = None,
        raw_model_output: dict[str, object] | None = None,
        raw_model_outputs: Sequence[dict[str, object]] = (),
        related_mineru_results: Sequence[
            tuple[ContractReviewSourceFile, MineruParseResult]
        ] = (),
        report_pdf: GeneratedReportPdf | None = None,
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
        for agent_output in raw_model_outputs:
            await self.audit_repository.record_event(
                task_id=task_id,
                event_type="contract_review_agent_raw_output",
                payload=agent_output,
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

        for related_file, related_result in related_mineru_results:
            await self._store_mineru_artifacts(
                task_id,
                related_result,
                scope="related",
                source_filename=related_file.filename,
            )

        if markdown:
            await self.snapshot_repository.save_paragraphs(
                task_id=task_id,
                paragraphs=_paragraph_payloads(markdown),
            )

        if report_pdf is not None:
            report_key = await self._store_report_pdf(task_id, report_pdf)
            await self._save_document_metadata(
                task_id=task_id,
                document_type="contract_review_report_pdf",
                filename=report_pdf.filename,
                content_type=report_pdf.content_type,
                content=report_pdf.content,
                object_key=report_key,
                mineru_batch_id=None,
            )
            if isinstance(response, ContractReviewReportResponse):
                # 同一响应对象随后进入快照与 API 序列化，确保两侧元数据一致。
                response.report_document = report_pdf.to_document_info(task_id)

        await self.snapshot_repository.save_context_snapshot(
            task_id=task_id,
            snapshot=_context_snapshot_payload(response),
        )
        await self.audit_repository.record_event(
            task_id=task_id,
            event_type="contract_review_persist_completed",
            payload={},
        )

    async def _store_report_pdf(
        self,
        task_id: str,
        report_pdf: GeneratedReportPdf,
    ) -> str:
        key = f"contract-reviews/{task_id}/reports/{_safe_object_name(report_pdf.filename)}"
        return await self.object_storage.put_bytes(
            key=key,
            content=report_pdf.content,
            content_type=report_pdf.content_type,
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
        # 文件名不具备唯一性，加入内容摘要避免同名附件覆盖已有 MinIO 对象。
        content_digest = hashlib.sha256(related_file.content).hexdigest()[:12]
        key = (
            f"contract-reviews/{task_id}/source/related/"
            f"{content_digest}-{safe_filename}"
        )
        return await self.object_storage.put_bytes(
            key=key,
            content=related_file.content,
            content_type=related_file.content_type,
        )

    async def _store_mineru_artifacts(
        self,
        task_id: str,
        mineru_result: MineruParseResult,
        *,
        scope: str = "main",
        source_filename: str | None = None,
    ) -> None:
        prefix = f"contract-reviews/{task_id}/mineru"
        if scope == "related":
            prefix = f"{prefix}/related"
        zip_key = f"{prefix}/{mineru_result.batch_id}/result.zip"
        markdown_key = f"{prefix}/{mineru_result.batch_id}/full.md"
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
                "scope": scope,
                "source_filename": source_filename,
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


def _context_snapshot_payload(
    response: ContractBackgroundResponse | ContractReviewReportResponse,
) -> dict[str, object]:
    if isinstance(response, ContractReviewReportResponse):
        background = response.background
        # API 使用 complete 表达报告完整性，任务表沿用既有 succeeded/partial 状态语义。
        task_status = "succeeded" if response.status == "complete" else response.status
        return {
            "background_card": background.background_card.model_dump(mode="json"),
            "contract_category": background.contract_category,
            "related_documents": [
                document.model_dump(mode="json") for document in background.related_documents
            ],
            "pitfalls": [pitfall.model_dump(mode="json") for pitfall in background.pitfalls],
            "status": task_status,
            "full_report": response.model_dump(mode="json"),
        }
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
