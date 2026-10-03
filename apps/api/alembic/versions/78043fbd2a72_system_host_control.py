"""system host control

Revision ID: 78043fbd2a72
Revises: 5a2bfcc2fe38
Create Date: 2026-10-03 03:34:51.571900
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "78043fbd2a72"
down_revision: str | None = "5a2bfcc2fe38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=True),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "system_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("principal_id", sa.String(128), nullable=False),
        sa.Column("auth_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("boot_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "system_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("principal_id", sa.String(128), nullable=False),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("target", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("system_audit")
    op.drop_table("system_jobs")
    op.drop_table("system_control")
