"""system agent UI provisioning

Revision ID: e5a7515cc663
Revises: 78043fbd2a72
Create Date: 2026-10-03 04:37:57.576149
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5a7515cc663"
down_revision: str | None = "78043fbd2a72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_provision_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inventory", sa.JSON(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "system_provision_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("principal_id", sa.String(128), nullable=False),
        sa.Column("auth_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(128), unique=True, nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_system_provision_jobs_state", "system_provision_jobs", ["state"])


def downgrade() -> None:
    op.drop_index("ix_system_provision_jobs_state", "system_provision_jobs")
    op.drop_table("system_provision_jobs")
    op.drop_table("system_provision_control")
