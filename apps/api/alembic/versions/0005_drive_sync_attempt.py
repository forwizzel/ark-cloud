"""Add Drive catalog sync attempt identity.

Revision ID: 0005_drive_sync_attempt
Revises: 0004_drive_connection_generation
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_drive_sync_attempt"
down_revision: str | None = "0004_drive_connection_generation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "google_drive_catalog_syncs",
        sa.Column("attempt_id", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("google_drive_catalog_syncs", "attempt_id")
