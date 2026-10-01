import importlib.util
from datetime import UTC, datetime
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select

from app.models import LocalUser, StorageControl, StorageGrant, StorageLocation
from app.services.local_storage import RootConfig
from app.services.storage_access import registration


def test_migration_preserves_existing_private_and_assigned_access(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "migration.db"))
    roots = [
        RootConfig(
            id="personal",
            label="My files",
            path="/srv/ark-storage/personal",
            device=1,
            inode=2,
            kind="managed",
        ),
        RootConfig(
            id="photos",
            label="Photos",
            path="/srv/ark-storage/photos",
            device=1,
            inode=3,
            kind="assigned",
            owner="member",
            read_only=True,
        ),
    ]
    with engine.begin() as connection:
        LocalUser.__table__.create(connection)
        StorageControl.__table__.create(connection)
        for name in ("admin", "member"):
            connection.execute(
                LocalUser.__table__.insert().values(
                    id=name,
                    username=name,
                    role="admin" if name == "admin" else "member",
                    active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
        connection.execute(
            StorageControl.__table__.insert().values(
                id=1,
                snapshot={"roots": [root.model_dump() for root in roots]},
                blocked_roots=[],
            )
        )
        file = Path(__file__).parents[1] / "alembic/versions/17a20903cc25_storage_access_grants.py"
        spec = importlib.util.spec_from_file_location("access_migration", file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        permissions = list(
            connection.execute(
                select(
                    StorageGrant.location_id,
                    StorageGrant.principal_id,
                    StorageGrant.level,
                )
            )
        )
        assert set(permissions) == {
            (registration(roots[0]), "admin", "write"),
            (registration(roots[0]), "member", "write"),
            (registration(roots[1]), "member", "read"),
        }
        assert connection.scalar(select(StorageLocation.retired).limit(1)) is False
    engine.dispose()
