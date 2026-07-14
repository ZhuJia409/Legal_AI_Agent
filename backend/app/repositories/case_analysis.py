from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import CaseAnalysisSnapshot


@dataclass(frozen=True, slots=True)
class CaseAnalysisRecord:
    analysis_id: str
    title: str | None
    status: str
    risk_level: str
    response_payload: dict[str, object]
    document_filename: str
    document_content_type: str
    document_size_bytes: int
    document_sha256: str
    document_object_key: str
    created_at: datetime
    updated_at: datetime


class SqlAlchemyCaseAnalysisRepository:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.session_factory = session_factory

    async def save(self, **values: object) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                await session.merge(CaseAnalysisSnapshot(**values))

    async def list_history(self, *, limit: int = 50) -> list[CaseAnalysisRecord]:
        safe_limit = max(1, min(limit, 50))
        async with self.session_factory() as session:
            result = await session.execute(
                select(CaseAnalysisSnapshot)
                .order_by(CaseAnalysisSnapshot.created_at.desc())
                .limit(safe_limit)
            )
            return [self._to_record(item) for item in result.scalars().all()]

    async def get(self, analysis_id: str) -> CaseAnalysisRecord | None:
        async with self.session_factory() as session:
            item = await session.get(CaseAnalysisSnapshot, analysis_id)
            return self._to_record(item) if item is not None else None

    @staticmethod
    def _to_record(item: CaseAnalysisSnapshot) -> CaseAnalysisRecord:
        return CaseAnalysisRecord(
            analysis_id=item.analysis_id,
            title=item.title,
            status=item.status,
            risk_level=item.risk_level,
            response_payload=item.response_payload,
            document_filename=item.document_filename,
            document_content_type=item.document_content_type,
            document_size_bytes=item.document_size_bytes,
            document_sha256=item.document_sha256,
            document_object_key=item.document_object_key,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
