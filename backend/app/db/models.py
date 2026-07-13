from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ReviewTask(Base):
    __tablename__ = "review_task"

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="succeeded")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ReviewDocument(Base):
    __tablename__ = "review_document"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("review_task.task_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    mineru_batch_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ContractParagraph(Base):
    __tablename__ = "contract_paragraph"

    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("review_task.task_id", ondelete="CASCADE"),
        primary_key=True,
    )
    paragraph_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    clause_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    paragraph_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)


class ContextSnapshot(Base):
    __tablename__ = "context_snapshot"

    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("review_task.task_id", ondelete="CASCADE"),
        primary_key=True,
    )
    contract_category: Mapped[str] = mapped_column(String(64), nullable=False)
    background_card: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    related_documents: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    pitfalls: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    snapshot_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
