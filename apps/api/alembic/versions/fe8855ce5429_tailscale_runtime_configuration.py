"""tailscale runtime configuration

Revision ID: fe8855ce5429
Revises: 17a20903cc25
Create Date: 2026-10-02 06:11:54.242764
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fe8855ce5429"
down_revision: str | None = "17a20903cc25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tailscale_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=True),
        sa.Column("configured_override", sa.Boolean(), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("tailnet", sa.String(320), nullable=False),
        sa.Column("desired_enabled", sa.Boolean(), nullable=False),
        sa.Column("disconnect", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("principal_id", sa.String(128), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("integration_state", sa.String(32), nullable=False),
        sa.Column("integration_message", sa.String(500), nullable=True),
        sa.Column("integration_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auth_key_encrypted", sa.Text(), nullable=True),
        sa.Column("auth_key_id", sa.String(128), nullable=True),
        sa.Column("auth_key_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("tailscale_control")
