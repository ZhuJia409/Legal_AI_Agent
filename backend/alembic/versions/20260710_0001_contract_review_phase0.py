"""add contract background review persistence tables

Revision ID: 20260710_0001
Revises:
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260710_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_task",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_table(
        "review_document",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("mineru_batch_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["review_task.task_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_document_task_id", "review_document", ["task_id"])
    op.create_table(
        "contract_paragraph",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("paragraph_id", sa.String(length=32), nullable=False),
        sa.Column("clause_path", sa.String(length=512), nullable=True),
        sa.Column("paragraph_index", sa.Integer(), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["review_task.task_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id", "paragraph_id"),
    )
    op.create_table(
        "context_snapshot",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("contract_category", sa.String(length=64), nullable=False),
        sa.Column("background_card", sa.JSON(), nullable=False),
        sa.Column("related_documents", sa.JSON(), nullable=False),
        sa.Column("pitfalls", sa.JSON(), nullable=False),
        sa.Column("snapshot_payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["review_task.task_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id"),
    )


def downgrade() -> None:
    op.drop_table("context_snapshot")
    op.drop_table("contract_paragraph")
    op.drop_index("ix_review_document_task_id", table_name="review_document")
    op.drop_table("review_document")
    op.drop_table("review_task")
