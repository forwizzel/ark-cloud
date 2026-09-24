"""Add the Drive metadata workspace.

Revision ID: 0006_drive_workspace
Revises: 0005_drive_sync_attempt
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_drive_workspace"
down_revision: str | None = "0005_drive_sync_attempt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "google_drive_connections",
        sa.Column("root_folder_id", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "google_drive_catalog_items",
        sa.Column("starred", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "google_drive_catalog_items",
        sa.Column("owned_by_me", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_index(
        "ix_drive_catalog_principal_starred",
        "google_drive_catalog_items",
        ["principal_id", "starred", "drive_file_id"],
    )
    for column in (
        sa.Column("catalog_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=True),
        sa.Column("phase", sa.String(length=32), nullable=True),
        sa.Column("processed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=True),
        sa.Column("retryable", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("recovery", sa.Boolean(), server_default=sa.false(), nullable=False),
    ):
        op.add_column("google_drive_catalog_syncs", column)

    syncs = sa.table(
        "google_drive_catalog_syncs",
        sa.column("change_page_token", sa.Text()),
        sa.column("attempt_id", sa.String(length=36)),
        sa.column("status", sa.String(length=32)),
        sa.column("phase", sa.String(length=32)),
        sa.column("processed_count", sa.Integer()),
        sa.column("total_count", sa.Integer()),
        sa.column("retryable", sa.Boolean()),
        sa.column("recovery", sa.Boolean()),
        sa.column("last_error", sa.String(length=500)),
    )
    op.execute(
        syncs.update().values(
            change_page_token=None,
            attempt_id=None,
            status="error",
            phase="failed",
            processed_count=0,
            total_count=None,
            retryable=True,
            recovery=True,
            last_error=(
                "The Drive catalog metadata format changed. Synchronize to rebuild the catalog."
            ),
        )
    )

    op.create_table(
        "google_drive_parent_edges",
        sa.Column("principal_id", sa.String(length=128), nullable=False),
        sa.Column("child_file_id", sa.String(length=256), nullable=False),
        sa.Column("parent_file_id", sa.String(length=256), nullable=False),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["google_drive_connections.principal_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("principal_id", "child_file_id", "parent_file_id"),
    )
    op.create_index(
        "ix_drive_parent_principal_parent",
        "google_drive_parent_edges",
        ["principal_id", "parent_file_id", "child_file_id"],
    )
    op.create_table(
        "google_drive_saved_searches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("principal_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("query", sa.String(length=200), nullable=True),
        sa.Column("view", sa.String(length=16), server_default="all", nullable=False),
        sa.Column("kind", sa.String(length=16), server_default="all", nullable=False),
        sa.Column("parent_id", sa.String(length=256), nullable=True),
        sa.Column("modified_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("modified_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("min_size", sa.BigInteger(), nullable=True),
        sa.Column("max_size", sa.BigInteger(), nullable=True),
        sa.Column("starred", sa.Boolean(), nullable=True),
        sa.Column("ownership", sa.String(length=16), server_default="owned_by_me", nullable=False),
        sa.Column("sort", sa.String(length=16), server_default="modified", nullable=False),
        sa.Column("direction", sa.String(length=4), server_default="desc", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["google_drive_connections.principal_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_drive_saved_search_principal_created",
        "google_drive_saved_searches",
        ["principal_id", "created_at", "id"],
    )
    op.create_table(
        "google_drive_pinned_locations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("principal_id", sa.String(length=128), nullable=False),
        sa.Column("drive_folder_id", sa.String(length=256), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["google_drive_connections.principal_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "principal_id", "drive_folder_id", name="uq_drive_pin_principal_folder"
        ),
    )
    op.create_index(
        "ix_drive_pin_principal_created",
        "google_drive_pinned_locations",
        ["principal_id", "created_at", "id"],
    )
    op.create_table(
        "google_drive_sync_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("principal_id", sa.String(length=128), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("processed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=True),
        sa.Column("retryable", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("recovery", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["google_drive_connections.principal_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_drive_attempt_principal_started",
        "google_drive_sync_attempts",
        ["principal_id", "started_at", "id"],
    )
    op.create_table(
        "google_drive_activities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("principal_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("drive_file_id", sa.String(length=256), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=True),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["google_drive_connections.principal_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_drive_activity_principal_observed",
        "google_drive_activities",
        ["principal_id", "observed_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_drive_activity_principal_observed", table_name="google_drive_activities")
    op.drop_table("google_drive_activities")
    op.drop_index("ix_drive_attempt_principal_started", table_name="google_drive_sync_attempts")
    op.drop_table("google_drive_sync_attempts")
    op.drop_index("ix_drive_pin_principal_created", table_name="google_drive_pinned_locations")
    op.drop_table("google_drive_pinned_locations")
    op.drop_index(
        "ix_drive_saved_search_principal_created", table_name="google_drive_saved_searches"
    )
    op.drop_table("google_drive_saved_searches")
    op.drop_index("ix_drive_parent_principal_parent", table_name="google_drive_parent_edges")
    op.drop_table("google_drive_parent_edges")
    for column in (
        "recovery",
        "retryable",
        "total_count",
        "processed_count",
        "phase",
        "mode",
        "catalog_revision",
    ):
        op.drop_column("google_drive_catalog_syncs", column)
    op.drop_index("ix_drive_catalog_principal_starred", table_name="google_drive_catalog_items")
    op.drop_column("google_drive_catalog_items", "owned_by_me")
    op.drop_column("google_drive_catalog_items", "starred")
    op.drop_column("google_drive_connections", "root_folder_id")
