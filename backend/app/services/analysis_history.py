from __future__ import annotations

from typing import Protocol

from pydantic import ValidationError

from app.repositories.case_analysis import CaseAnalysisRecord
from app.repositories.contract_review import ContractReviewHistoryRecord
from app.schemas.case_analysis import (
    CaseAnalysisHistoryItem,
    CaseAnalysisHistoryResponse,
    CaseAnalysisResponse,
)
from app.schemas.contract_review import (
    ContractReviewHistoryItem,
    ContractReviewHistoryResponse,
    ContractReviewReportResponse,
)


class HistoryNotFoundError(LookupError):
    """历史快照不存在。"""


class HistorySnapshotError(RuntimeError):
    """历史 JSON 无法通过当前公开 schema 校验。"""


class ContractHistoryRepositoryProtocol(Protocol):
    async def list_report_history(
        self, *, limit: int
    ) -> list[ContractReviewHistoryRecord]: ...

    async def get_report_snapshot(self, task_id: str) -> object | None: ...


class CaseHistoryRepositoryProtocol(Protocol):
    async def list_history(self, *, limit: int) -> list[CaseAnalysisRecord]: ...

    async def get(self, analysis_id: str) -> CaseAnalysisRecord | None: ...


class ContractReviewHistoryService:
    def __init__(self, repository: ContractHistoryRepositoryProtocol) -> None:
        self.repository = repository

    async def list_history(self) -> ContractReviewHistoryResponse:
        records = await self.repository.list_report_history(limit=50)
        return ContractReviewHistoryResponse(
            items=[
                ContractReviewHistoryItem(
                    task_id=item.task_id,
                    title=item.title,
                    status="partial" if item.status == "partial" else "complete",
                    risk_level=item.overall_risk_level,  # type: ignore[arg-type]
                    created_at=item.created_at,
                )
                for item in records
            ]
        )

    async def get_report(self, task_id: str) -> ContractReviewReportResponse:
        snapshot = await self.repository.get_report_snapshot(task_id)
        if snapshot is None:
            raise HistoryNotFoundError("contract review history not found")
        try:
            return ContractReviewReportResponse.model_validate(snapshot)
        except ValidationError as exc:
            raise HistorySnapshotError("contract review snapshot is invalid") from exc


class CaseAnalysisHistoryService:
    def __init__(self, repository: CaseHistoryRepositoryProtocol) -> None:
        self.repository = repository

    async def list_history(self) -> CaseAnalysisHistoryResponse:
        records = await self.repository.list_history(limit=50)
        return CaseAnalysisHistoryResponse(
            items=[
                CaseAnalysisHistoryItem(
                    analysis_id=item.analysis_id,
                    title=item.title,
                    status=item.status,  # type: ignore[arg-type]
                    risk_level=item.risk_level,  # type: ignore[arg-type]
                    created_at=item.created_at,
                )
                for item in records
            ]
        )

    async def get_analysis(self, analysis_id: str) -> CaseAnalysisResponse:
        record = await self.repository.get(analysis_id)
        if record is None:
            raise HistoryNotFoundError("case analysis history not found")
        try:
            return CaseAnalysisResponse.model_validate(record.response_payload)
        except ValidationError as exc:
            raise HistorySnapshotError("case analysis snapshot is invalid") from exc
