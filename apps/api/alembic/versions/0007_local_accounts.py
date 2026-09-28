"""Add persistent local accounts and import the legacy single-user identity.

Revision ID: 0007_local_accounts
Revises: 0006_drive_workspace
"""

import os
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "0007_local_accounts"
down_revision = "0006_drive_workspace"
branch_labels = None
depends_on = None

CHILDREN = (
    "google_drive_catalog_syncs",
    "google_drive_catalog_items",
    "google_drive_parent_edges",
    "google_drive_saved_searches",
    "google_drive_pinned_locations",
    "google_drive_sync_attempts",
    "google_drive_activities",
)


def upgrade() -> None:
    op.create_table(
        "local_users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(128), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("invite_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("invite_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "bootstrap_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "local_session_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("secret", sa.String(128), nullable=False),
    )

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if bind.dialect.name == "postgresql":
        for table in CHILDREN:
            foreign_key = next(
                key
                for key in inspector.get_foreign_keys(table)
                if key["referred_table"] == "google_drive_connections"
                and key["constrained_columns"] == ["principal_id"]
            )
            op.drop_constraint(foreign_key["name"], table, type_="foreignkey")
            op.create_foreign_key(
                foreign_key["name"],
                table,
                "google_drive_connections",
                ["principal_id"],
                ["principal_id"],
                ondelete="CASCADE",
                onupdate="CASCADE",
            )

    username = os.getenv("ARK_AUTH_USERNAME", "").strip()
    password_hash = os.getenv("ARK_AUTH_PASSWORD_HASH", "").strip().strip("'\"")
    owners = set(
        bind.execute(sa.text("SELECT principal_id FROM google_drive_connections")).scalars()
    )
    if owners - {username}:
        raise RuntimeError("Unrecognized legacy Drive owner; restore credentials before upgrading.")
    if bool(username) != bool(password_hash) or (owners and not username):
        raise RuntimeError(
            "Set both legacy ARK_AUTH_USERNAME and ARK_AUTH_PASSWORD_HASH before upgrading."
        )
    if username:
        if len(username) > 128 or not password_hash.startswith("$argon2id$"):
            raise RuntimeError(
                "Legacy username/hash is invalid; correct the configuration before upgrading."
            )
        user_id = str(uuid.uuid4())
        timestamp = datetime.now(UTC)
        bind.execute(
            sa.text(
                "INSERT INTO local_users "
                "(id, username, password_hash, role, active, created_at, updated_at) "
                "VALUES (:id, :username, :password_hash, 'admin', true, :now, :now)"
            ),
            {
                "id": user_id,
                "username": username.casefold(),
                "password_hash": password_hash,
                "now": timestamp,
            },
        )
        if bind.dialect.name == "sqlite":
            for table in CHILDREN:
                bind.execute(
                    sa.text(f"UPDATE {table} SET principal_id=:id WHERE principal_id=:old"),
                    {"id": user_id, "old": username},
                )
        bind.execute(
            sa.text("UPDATE google_drive_connections SET principal_id=:id WHERE principal_id=:old"),
            {"id": user_id, "old": username},
        )

    # Old session cookies refer to a username, so no old session can survive the identity change.
    bind.execute(sa.text("DELETE FROM auth_sessions"))
    if bind.dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_auth_sessions_user",
            "auth_sessions",
            "local_users",
            ["principal_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_drive_connections_user",
            "google_drive_connections",
            "local_users",
            ["principal_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    raise RuntimeError("Account identity migration cannot be safely reversed; restore a backup.")
