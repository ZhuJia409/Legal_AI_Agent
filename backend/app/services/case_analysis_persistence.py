from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from app.repositories.case_analysis import CaseAnalysisRecord
from app.schemas.case_analysis import CaseAnalysisResponse
from app.services.case_analysis_document import GeneratedCaseDocument
from app.services.object_storage import ObjectStorageReadError


class CaseAnalysisRepositoryProtocol(Protocol):
    async def save(self, **values: object) -> None: ...

    async def get(self, analysis_id: str) -> CaseAnalysisRecord | None: ...


class CaseObjectStorageProtocol(Protocol):
    async def put_bytes(self, *, key: str, content: bytes, content_type: str) -> str: ...

    async def get_bytes(self, *, key: str) -> bytes: ...


class CaseAnalysisDocumentNotFoundError(LookupError):
    """案件文书草稿不存在。"""


class CaseAnalysisDocumentReadError(RuntimeError):
    """案件文书草稿无法读取或完整性校验失败。"""


@dataclass(frozen=True, slots=True)
class CaseAnalysisDocumentDownload:
    record: CaseAnalysisRecord
    content: bytes


class CaseAnalysisPersistenceService:
    def __init__(
        self,
        *,
        repository: CaseAnalysisRepositoryProtocol,
        object_storage: CaseObjectStorageProtocol,
    ) -> None:
        self.repository = repository
        self.object_storage = object_storage

    async def persist(
        self,
        *,
        title: str | None,
        response: CaseAnalysisResponse,
        document: GeneratedCaseDocument,
    ) -> None:
        object_key = f"case-analyses/{response.analysis_id}/documents/{document.filename}"
        await self.object_storage.put_bytes(
            key=object_key,
            content=document.content,
            content_type=document.content_type,
        )
        # 先回填公开元数据再序列化，保证历史详情与当次响应一致。
        response.draft_document = document.to_document_info(response.analysis_id)
        await self.repository.save(
            analysis_id=response.analysis_id,
            title=title,
            status=response.status,
            risk_level=response.risk_level,
            response_payload=response.model_dump(mode="json"),
            document_filename=document.filename,
            document_content_type=document.content_type,
            document_size_bytes=len(document.content),
            document_sha256=document.sha256,
            document_object_key=object_key,
        )


class CaseAnalysisStoredDocumentService:
    def __init__(
        self,
        *,
        repository: CaseAnalysisRepositoryProtocol,
        object_storage: CaseObjectStorageProtocol,
    ) -> None:
        self.repository = repository
        self.object_storage = object_storage

    async def get_document(self, analysis_id: str) -> CaseAnalysisDocumentDownload:
        record = await self.repository.get(analysis_id)
        if record is None:
            raise CaseAnalysisDocumentNotFoundError("case analysis document not found")
        try:
            content = await self.object_storage.get_bytes(key=record.document_object_key)
        except ObjectStorageReadError as exc:
            raise CaseAnalysisDocumentReadError("case analysis document read failed") from exc
        if (
            len(content) != record.document_size_bytes
            or hashlib.sha256(content).hexdigest() != record.document_sha256
        ):
            raise CaseAnalysisDocumentReadError("case analysis document integrity check failed")
        return CaseAnalysisDocumentDownload(record=record, content=content)
