"""合同审查报告文档的可信读取边界。"""

import hashlib
from dataclasses import dataclass
from typing import Protocol

from app.repositories.contract_review import ReviewDocumentRecord
from app.services.object_storage import ObjectStorageReadError

REPORT_DOCUMENT_TYPE = "contract_review_report_pdf"


class ReportDocumentNotFoundError(LookupError):
    """任务没有可下载的合同审查 PDF 元数据。"""


class ReportDocumentReadError(RuntimeError):
    """PDF 对象无法读取或完整性校验失败。"""


class ReviewDocumentRepositoryProtocol(Protocol):
    async def get_latest_document(
        self,
        *,
        task_id: str,
        document_type: str,
    ) -> ReviewDocumentRecord | None: ...


class ReadableObjectStorageProtocol(Protocol):
    async def get_bytes(self, *, key: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class ReportDocumentDownload:
    metadata: ReviewDocumentRecord
    content: bytes


class ContractReviewDocumentService:
    """读取报告 PDF，并在交给 HTTP 层前验证长度和内容摘要。"""

    def __init__(
        self,
        *,
        repository: ReviewDocumentRepositoryProtocol,
        object_storage: ReadableObjectStorageProtocol,
    ) -> None:
        self._repository = repository
        self._object_storage = object_storage

    async def get_report_pdf(self, task_id: str) -> ReportDocumentDownload:
        metadata = await self._repository.get_latest_document(
            task_id=task_id,
            document_type=REPORT_DOCUMENT_TYPE,
        )
        if metadata is None:
            raise ReportDocumentNotFoundError("合同审查报告文档不存在")

        try:
            content = await self._object_storage.get_bytes(key=metadata.object_key)
        except ObjectStorageReadError as exc:
            raise ReportDocumentReadError("合同审查报告文档读取失败") from exc

        digest = hashlib.sha256(content).hexdigest()
        if len(content) != metadata.size_bytes or digest != metadata.sha256:
            # 法律报告必须与登记摘要一致，损坏对象不得继续下发。
            raise ReportDocumentReadError("合同审查报告文档完整性校验失败")
        return ReportDocumentDownload(metadata=metadata, content=content)
