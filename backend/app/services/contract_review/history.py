from typing import Protocol

from pydantic import ValidationError

from app.repositories.contract_review import ContractReviewHistoryRecord
from app.schemas.contract_review import (
    ContractReviewHistoryItem,
    ContractReviewHistoryResponse,
    ContractReviewReportResponse,
)
from app.services.history import HistoryNotFoundError, HistorySnapshotError


class ContractHistoryRepositoryProtocol(Protocol):
    async def list_report_history(
        self, *, limit: int
    ) -> list[ContractReviewHistoryRecord]: ...

    async def get_report_snapshot(self, task_id: str) -> object | None: ...


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
