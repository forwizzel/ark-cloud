"""Add the Google Drive metadata catalog.

Revision ID: 0003_drive_catalog
Revises: cacd4e250194
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_drive_catalog"
down_revision: str | None = "cacd4e250194"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "google_drive_catalog_syncs",
        sa.Column("principal_id", sa.String(length=128), nullable=False),
        sa.Column("change_page_token", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["google_drive_connections.principal_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("principal_id"),
    )
    op.create_table(
        "google_drive_catalog_items",
        sa.Column("principal_id", sa.String(length=128), nullable=False),
        sa.Column("drive_file_id", sa.String(length=256), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_search", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("drive_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("drive_modified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("web_url", sa.Text(), nullable=False),
        sa.Column("parent_ids", sa.JSON(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["google_drive_connections.principal_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("principal_id", "drive_file_id"),
        sa.UniqueConstraint(
            "principal_id", "drive_file_id", name="uq_drive_catalog_principal_file"
        ),
    )
    op.create_index(
        "ix_drive_catalog_principal_modified",
        "google_drive_catalog_items",
        ["principal_id", "drive_modified_at", "drive_file_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_drive_catalog_principal_modified", table_name="google_drive_catalog_items")
    op.drop_table("google_drive_catalog_items")
    op.drop_table("google_drive_catalog_syncs")
