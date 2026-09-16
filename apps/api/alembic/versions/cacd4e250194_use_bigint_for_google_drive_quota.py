"""use bigint for google drive quota

Revision ID: cacd4e250194
Revises: 0002_auth_google_drive
Create Date: 2026-09-16 23:38:14.232990
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "cacd4e250194"
down_revision: str | None = "0002_auth_google_drive"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "google_drive_connections",
        "used_bytes",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )
    op.alter_column(
        "google_drive_connections",
        "total_bytes",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "google_drive_connections",
        "total_bytes",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
    op.alter_column(
        "google_drive_connections",
        "used_bytes",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
