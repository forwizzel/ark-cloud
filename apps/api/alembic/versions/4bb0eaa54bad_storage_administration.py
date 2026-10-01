"""storage administration

Revision ID: 4bb0eaa54bad
Revises: 0008_login_attempt_cleanup_index
Create Date: 2026-09-30 05:16:40.642552
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4bb0eaa54bad"
down_revision: str | None = "0008_login_attempt_cleanup_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "storage_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64)),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("upload_max_bytes", sa.BigInteger()),
        sa.Column("blocked_roots", sa.JSON(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "storage_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("principal_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_storage_jobs_state", "storage_jobs", ["state"])
    op.create_table(
        "storage_preferences",
        sa.Column(
            "principal_id",
            sa.String(128),
            sa.ForeignKey("local_users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("root_id", sa.String(40)),
        sa.Column("path", sa.String(2048), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("storage_preferences")
    op.drop_table("storage_jobs")
    op.drop_table("storage_control")
