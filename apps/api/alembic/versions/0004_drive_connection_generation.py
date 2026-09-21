"""Add a Drive connection generation for sync concurrency.

Revision ID: 0004_drive_connection_generation
Revises: 0003_drive_catalog
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_drive_connection_generation"
down_revision: str | None = "0003_drive_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "google_drive_connections",
        sa.Column("catalog_generation", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("google_drive_connections", "catalog_generation")
