from datetime import UTC, datetime, timedelta

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import Column, ForeignKey, MetaData, String, Table, create_engine, inspect, select

from app.main import app
from app.models import (
    AuthSession,
    Base,
    LocalUser,
    StorageControl,
    StorageGrant,
    StorageJob,
    StorageLocation,
    StoragePreference,
    TailscaleControl,
)


@pytest.mark.parametrize(
    "path",
    [
        "/integrations/google-drive/connect",
        "/integrations/google-drive/oauth/callback",
        "/integrations/google-drive/status",
        "/integrations/google-drive/items",
        "/search?q=example",
    ],
)
def test_retired_routes_are_not_registered(path):
    client = TestClient(app)
    assert client.get(path).status_code == 404
    assert not any("google-drive" in route for route in app.openapi()["paths"])
    assert "GoogleDriveSummary" not in app.openapi()["components"]["schemas"]


def test_removal_migration_deletes_provider_data_and_preserves_control_plane():
    engine = create_engine("sqlite://")
    config = Config("alembic.ini")
    config.set_main_option("path_separator", "os")
    revision = ScriptDirectory.from_config(config).get_revision("5a2bfcc2fe38")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        Base.metadata.create_all(connection)
        connection.exec_driver_sql(
            "ALTER TABLE auth_sessions ADD COLUMN oauth_state_hash VARCHAR(64)"
        )
        connection.exec_driver_sql(
            "ALTER TABLE auth_sessions ADD COLUMN oauth_state_expires_at DATETIME"
        )
        timestamp = datetime.now(UTC)
        connection.execute(
            LocalUser.__table__.insert().values(
                id="account",
                username="owner",
                password_hash="retained-password-hash",
                role="admin",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        connection.execute(
            AuthSession.__table__.insert().values(
                id="session",
                principal_id="account",
                token_hash="t" * 64,
                csrf_hash="c" * 64,
                expires_at=timestamp + timedelta(days=1),
                created_at=timestamp,
                last_used_at=timestamp,
            )
        )
        connection.exec_driver_sql("UPDATE auth_sessions SET oauth_state_hash = 'obsolete-state'")
        connection.execute(
            StorageControl.__table__.insert().values(id=1, snapshot={"roots": ["local"]})
        )
        connection.execute(
            StorageLocation.__table__.insert().values(
                id="registration", root_id="local", kind="managed"
            )
        )
        connection.execute(
            StorageGrant.__table__.insert().values(
                location_id="registration", principal_id="account", level="write", version="grant"
            )
        )
        connection.execute(
            StoragePreference.__table__.insert().values(
                principal_id="account", root_id="local", path="Documents"
            )
        )
        connection.execute(
            StorageJob.__table__.insert().values(
                id="job",
                principal_id="account",
                action="check",
                payload={"root_id": "local"},
                state="completed",
                message="Verified",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        connection.execute(
            TailscaleControl.__table__.insert().values(
                id=1,
                api_key_encrypted="retained-tailscale-credential",
                desired_enabled=True,
                snapshot={"state": "connected"},
            )
        )
        preserved = {
            table.name: list(connection.execute(select(table)).mappings())
            for table in Base.metadata.sorted_tables
        }

        # Recreate the retired connection/child dependency graph independently of
        # the removed ORM models, with real populated rows and enforced FKs.
        metadata = MetaData()
        parent = Table(
            "google_drive_connections",
            metadata,
            Column("principal_id", String, primary_key=True),
            Column("refresh_token_encrypted", String),
        )
        children = [
            Table(
                "google_drive_" + name,
                metadata,
                Column("principal_id", String, ForeignKey(parent.c.principal_id), primary_key=True),
            )
            for name in (
                "catalog_syncs",
                "catalog_items",
                "parent_edges",
                "saved_searches",
                "pinned_locations",
                "sync_attempts",
                "activities",
            )
        ]
        metadata.create_all(connection)
        connection.execute(
            parent.insert().values(
                principal_id="account", refresh_token_encrypted="retired-credential"
            )
        )
        for child in children:
            connection.execute(child.insert().values(principal_id="account"))
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.upgrade()
        inspector = inspect(connection)
        assert not any(name.startswith("google_drive_") for name in inspector.get_table_names())
        assert not any(
            column["name"].startswith("oauth_") for column in inspector.get_columns("auth_sessions")
        )
        for table in Base.metadata.sorted_tables:
            assert list(connection.execute(select(table)).mappings()) == preserved[table.name]
