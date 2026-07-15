from typing import Protocol

from pydantic import ValidationError

from app.repositories.case_analysis import CaseAnalysisRecord
from app.schemas.case_analysis import (
    CaseAnalysisHistoryItem,
    CaseAnalysisHistoryResponse,
    CaseAnalysisResponse,
)
from app.services.history import HistoryNotFoundError, HistorySnapshotError


class CaseHistoryRepositoryProtocol(Protocol):
    async def list_history(self, *, limit: int) -> list[CaseAnalysisRecord]: ...

    async def get(self, analysis_id: str) -> CaseAnalysisRecord | None: ...


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
