from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class CaseAnalysisSnapshot(Base):
    """案件分析结果与草稿文档的不可变历史快照。"""

    __tablename__ = "case_analysis_snapshot"

    analysis_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    response_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    document_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    document_content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    document_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
