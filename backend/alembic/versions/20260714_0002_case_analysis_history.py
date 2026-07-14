"""add case analysis history snapshots

Revision ID: 20260714_0002
Revises: 20260710_0001
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260714_0002"
down_revision: str | None = "20260710_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "case_analysis_snapshot",
        sa.Column("analysis_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("document_filename", sa.String(length=512), nullable=False),
        sa.Column("document_content_type", sa.String(length=255), nullable=False),
        sa.Column("document_size_bytes", sa.Integer(), nullable=False),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("document_object_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("analysis_id"),
    )
    op.create_index(
        "ix_case_analysis_snapshot_created_at",
        "case_analysis_snapshot",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_case_analysis_snapshot_created_at", table_name="case_analysis_snapshot")
    op.drop_table("case_analysis_snapshot")
