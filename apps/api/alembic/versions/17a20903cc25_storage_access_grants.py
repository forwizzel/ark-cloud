"""storage access grants

Revision ID: 17a20903cc25
Revises: 4bb0eaa54bad
Create Date: 2026-10-01 07:33:16.309150
"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid4, uuid5

import sqlalchemy as sa

from alembic import op

revision: str = "17a20903cc25"
down_revision: str | None = "4bb0eaa54bad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    locations = op.create_table(
        "storage_locations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("root_id", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("retired", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_index("ix_storage_locations_root_id", "storage_locations", ["root_id"])
    grants = op.create_table(
        "storage_grants",
        sa.Column(
            "location_id",
            sa.String(36),
            sa.ForeignKey("storage_locations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "principal_id",
            sa.String(128),
            sa.ForeignKey("local_users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("level", sa.String(8), nullable=False),
        sa.Column("version", sa.String(36), nullable=False),
    )
    connection = op.get_bind()
    users = sa.table("local_users", sa.column("id", sa.String), sa.column("active", sa.Boolean))
    active = list(connection.scalars(sa.select(users.c.id).where(users.c.active.is_(True))))
    control = sa.table("storage_control", sa.column("snapshot", sa.JSON))
    snapshot = connection.scalar(sa.select(control.c.snapshot)) or {}
    for root in snapshot.get("roots", []):
        # Must agree with the legacy registration key in the API and host CLI.
        name = (
            f"ark-storage:{root['id']}:{root['kind']}:{root['device']}:{root['inode']}:"
            f"{root.get('owner') or ''}"
        )
        identity = root.get("registration") or str(uuid5(NAMESPACE_URL, name))
        connection.execute(
            locations.insert().values(
                id=identity,
                root_id=root["id"],
                kind=root["kind"],
                retired=False,
                revision=0,
            )
        )
        recipients = active if root["kind"] == "managed" else [root.get("owner")]
        for recipient in recipients:
            if recipient in active:
                connection.execute(
                    grants.insert().values(
                        location_id=identity,
                        principal_id=recipient,
                        level="read" if root["read_only"] else "write",
                        version=str(uuid4()),
                    )
                )


def downgrade() -> None:
    op.drop_table("storage_grants")
    op.drop_table("storage_locations")
