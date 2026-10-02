"""remove google drive integration

Revision ID: 5a2bfcc2fe38
Revises: fe8855ce5429
Create Date: 2026-10-02 07:22:01.941638
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5a2bfcc2fe38"
down_revision: str | None = "fe8855ce5429"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Children precede their connection parent; no unrelated tables are cascaded.
    for table in (
        "google_drive_activities",
        "google_drive_sync_attempts",
        "google_drive_pinned_locations",
        "google_drive_saved_searches",
        "google_drive_parent_edges",
        "google_drive_catalog_items",
        "google_drive_catalog_syncs",
        "google_drive_connections",
    ):
        op.drop_table(table)
    op.drop_column("auth_sessions", "oauth_state_expires_at")
    op.drop_column("auth_sessions", "oauth_state_hash")


def downgrade() -> None:
    raise RuntimeError(
        "Removed integration credentials and metadata cannot be recovered by a downgrade; "
        "restore a database backup."
    )
