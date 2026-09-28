"""Index the login-attempt expiry window.

Revision ID: 0008_login_attempt_cleanup_index
Revises: 0007_local_accounts
"""

from alembic import op

revision = "0008_login_attempt_cleanup_index"
down_revision = "0007_local_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_login_attempts_window_started_at", "login_attempts", ["window_started_at"])


def downgrade() -> None:
    op.drop_index("ix_login_attempts_window_started_at", table_name="login_attempts")
