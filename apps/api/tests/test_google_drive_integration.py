import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from urllib.error import HTTPError

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.google_drive import (
    ActiveGoogleDriveSyncError,
    GoogleDriveError,
    GoogleDriveIntegration,
)
from app.models import (
    GoogleDriveActivity,
    GoogleDriveCatalogItem,
    GoogleDriveCatalogSync,
    GoogleDriveConnection,
    GoogleDriveParentEdge,
    GoogleDriveSyncAttempt,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, _: int) -> bytes:
        return json.dumps(self._payload).encode()


def google_settings() -> Settings:
    return Settings(
        database_url="sqlite://",
        auth_username="ark",
        auth_password_hash="$argon2id$v=19$m=65536,t=3,p=4$MDEyMzQ1Njc4OWFiY2RlZg$JmC0V7Lu4IfDtq2Thwygv94MPOxF4XL1Qb3afcF8dSo",
        session_secret="test",
        google_client_id="client",
        google_client_secret="secret",
        google_redirect_uri="http://127.0.0.1:5173/api/integrations/google-drive/oauth/callback",
        google_token_encryption_key=Fernet.generate_key().decode(),
    )


def test_google_drive_normalizes_cached_quota(monkeypatch, db_session: Session) -> None:
    responses = iter(
        [
            {
                "refresh_token": "refresh",
                "scope": "https://www.googleapis.com/auth/drive.metadata.readonly",
            },
            {"access_token": "access"},
            {
                "user": {"displayName": "Ark User", "emailAddress": "ark@example.test"},
                "storageQuota": {"usage": "5000000000", "limit": "15000000000"},
            },
        ]
    )
    monkeypatch.setattr(
        "app.integrations.google_drive.urlopen",
        lambda *_args, **_kwargs: FakeResponse(next(responses)),
    )
    integration = GoogleDriveIntegration(google_settings(), db_session)

    integration.exchange_code("ark", "code")
    summary = integration.summary("ark")

    assert summary.state == "healthy"
    assert summary.account_email == "ark@example.test"
    assert summary.used_bytes == 5_000_000_000
    assert summary.available_bytes == 10_000_000_000


def test_google_drive_is_not_configured_without_credentials(db_session: Session) -> None:
    integration = GoogleDriveIntegration(Settings(database_url="sqlite://"), db_session)

    assert integration.summary("ark").state == "not_configured"


def test_google_drive_builds_and_incrementally_updates_catalog(
    monkeypatch, db_session: Session
) -> None:
    responses = iter(
        [
            {
                "refresh_token": "refresh",
                "scope": "https://www.googleapis.com/auth/drive.metadata.readonly",
            },
            {"access_token": "access"},
            {
                "user": {"displayName": "Ark User", "emailAddress": "ark@example.test"},
                "storageQuota": {"usage": "10", "limit": "100"},
            },
            {"access_token": "access"},
            {"id": "opaque-root-id"},
            {"startPageToken": "changes-1"},
            {
                "files": [
                    {
                        "id": "file-1",
                        "name": "Tax Return.pdf",
                        "mimeType": "application/pdf",
                        "size": "42",
                        "createdTime": "2026-01-01T10:00:00Z",
                        "modifiedTime": "2026-02-01T10:00:00Z",
                        "parents": ["opaque-root-id"],
                        "trashed": False,
                        "ownedByMe": True,
                    },
                    {
                        "id": "shared-file",
                        "name": "Shared with me.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-02-01T10:00:00Z",
                        "parents": [],
                        "trashed": False,
                        "ownedByMe": False,
                    },
                ]
            },
            {"changes": [], "newStartPageToken": "changes-2"},
            {"access_token": "access"},
            {
                "changes": [
                    {
                        "fileId": "file-1",
                        "removed": False,
                        "file": {
                            "id": "file-1",
                            "name": "Final Tax Return.pdf",
                            "mimeType": "application/pdf",
                            "size": "50",
                            "createdTime": "2026-01-01T10:00:00Z",
                            "modifiedTime": "2026-03-01T10:00:00Z",
                            "parents": ["opaque-root-id"],
                            "trashed": False,
                            "ownedByMe": True,
                        },
                    },
                    {
                        "fileId": "never-cataloged-shared-file",
                        "removed": False,
                        "file": {
                            "id": "never-cataloged-shared-file",
                            "name": "Shared.txt",
                            "mimeType": "text/plain",
                            "modifiedTime": "2026-03-01T10:00:00Z",
                            "ownedByMe": False,
                        },
                    },
                ],
                "newStartPageToken": "changes-3",
            },
        ]
    )
    monkeypatch.setattr(
        "app.integrations.google_drive.urlopen",
        lambda *_args, **_kwargs: FakeResponse(next(responses)),
    )
    integration = GoogleDriveIntegration(google_settings(), db_session)
    integration.exchange_code("ark", "code")

    initial = integration.sync_catalog("ark")
    updated = integration.sync_catalog("ark")
    item = db_session.scalar(
        select(GoogleDriveCatalogItem).where(
            GoogleDriveCatalogItem.principal_id == "ark",
            GoogleDriveCatalogItem.drive_file_id == "file-1",
        )
    )

    assert initial.state == "ready"
    assert initial.item_count == 1
    assert updated.state == "ready"
    assert item is not None
    assert item.name == "Final Tax Return.pdf"
    assert item.size_bytes == 50
    assert item.web_url == "https://drive.google.com/open?id=file-1"
    assert item.parent_ids == ["root"]
    connection = db_session.get(GoogleDriveConnection, "ark")
    assert connection is not None and connection.root_folder_id == "opaque-root-id"
    assert db_session.get(GoogleDriveParentEdge, ("ark", "file-1", "root")) is not None
    event_types = list(
        db_session.scalars(
            select(GoogleDriveActivity.event_type).order_by(GoogleDriveActivity.observed_at)
        )
    )
    assert event_types.count("sync_completed") == 2
    assert event_types.count("modified") == 1
    assert event_types.count("removed") == 0
    assert "created" not in event_types


def test_failed_incremental_sync_preserves_existing_catalog(
    monkeypatch, db_session: Session
) -> None:
    responses = iter(
        [
            {
                "refresh_token": "refresh",
                "scope": "https://www.googleapis.com/auth/drive.metadata.readonly",
            },
            {"access_token": "access"},
            {
                "user": {"displayName": "Ark User", "emailAddress": "ark@example.test"},
                "storageQuota": {"usage": "10", "limit": "100"},
            },
            {"access_token": "access"},
            {"id": "opaque-root-id"},
            {"startPageToken": "changes-1"},
            {
                "files": [
                    {
                        "id": "file-1",
                        "name": "Existing.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                        "ownedByMe": True,
                    }
                ]
            },
            {"changes": [], "newStartPageToken": "changes-2"},
            {"access_token": "access"},
            {"changes": "invalid", "newStartPageToken": "changes-3"},
        ]
    )
    monkeypatch.setattr(
        "app.integrations.google_drive.urlopen",
        lambda *_args, **_kwargs: FakeResponse(next(responses)),
    )
    integration = GoogleDriveIntegration(google_settings(), db_session)
    integration.exchange_code("ark", "code")
    integration.sync_catalog("ark")

    try:
        integration.sync_catalog("ark")
    except GoogleDriveError:
        pass
    else:
        raise AssertionError("Invalid changes metadata should fail synchronization")

    assert integration.catalog_status("ark").state == "error"
    assert db_session.get(GoogleDriveCatalogItem, ("ark", "file-1")) is not None


def test_expired_change_token_recovers_with_atomic_full_replacement(
    monkeypatch, db_session: Session
) -> None:
    responses: list[dict[str, object] | Exception] = [
        {
            "refresh_token": "refresh",
            "scope": "https://www.googleapis.com/auth/drive.metadata.readonly",
        },
        {"access_token": "access"},
        {"user": {}, "storageQuota": {}},
        {"access_token": "access"},
        {"id": "opaque-root-id"},
        {"startPageToken": "one"},
        {
            "files": [
                {
                    "id": "old",
                    "name": "Old.txt",
                    "mimeType": "text/plain",
                    "modifiedTime": "2026-01-01T00:00:00Z",
                    "parents": ["opaque-root-id"],
                    "ownedByMe": True,
                }
            ]
        },
        {"changes": [], "newStartPageToken": "two"},
        {"access_token": "access"},
        HTTPError("https://www.googleapis.com/drive/v3/changes", 410, "Gone", {}, BytesIO()),
        {"startPageToken": "three"},
        {
            "files": [
                {
                    "id": "new",
                    "name": "New.pdf",
                    "mimeType": "application/pdf",
                    "modifiedTime": "2026-02-01T00:00:00Z",
                    "parents": ["opaque-root-id"],
                    "starred": True,
                    "ownedByMe": True,
                }
            ]
        },
        {"changes": [], "newStartPageToken": "four"},
        {"access_token": "access"},
        HTTPError("https://www.googleapis.com/drive/v3/changes", 410, "Gone", {}, BytesIO()),
        {"startPageToken": "five"},
        {"files": "invalid"},
    ]
    values = iter(responses)

    def urlopen(*_args, **_kwargs):
        value = next(values)
        if isinstance(value, Exception):
            raise value
        return FakeResponse(value)

    monkeypatch.setattr("app.integrations.google_drive.urlopen", urlopen)
    integration = GoogleDriveIntegration(google_settings(), db_session)
    integration.exchange_code("ark", "code")
    integration.sync_catalog("ark")
    result = integration.sync_catalog("ark")

    assert result.revision == 2
    assert result.mode == "recovery"
    assert result.recovery is True
    assert db_session.get(GoogleDriveCatalogItem, ("ark", "old")) is None
    new = db_session.get(GoogleDriveCatalogItem, ("ark", "new"))
    assert new is not None and new.starred is True
    assert db_session.get(GoogleDriveParentEdge, ("ark", "new", "root")) is not None
    sync = db_session.get(GoogleDriveCatalogSync, "ark")
    assert sync is not None and sync.change_page_token == "four"
    attempts = list(db_session.scalars(select(GoogleDriveSyncAttempt)))
    assert [attempt.status for attempt in attempts] == ["success", "success"]

    try:
        integration.sync_catalog("ark")
    except GoogleDriveError:
        pass
    else:
        raise AssertionError("A failed recovery scan should fail synchronization")
    assert db_session.get(GoogleDriveCatalogItem, ("ark", "new")) is not None
    assert db_session.get(GoogleDriveParentEdge, ("ark", "new", "root")) is not None
    failed_status = integration.catalog_status("ark")
    assert failed_status.revision == 2
    assert failed_status.state == "error"


def test_active_sync_is_rejected_and_stale_sync_is_recovered(
    monkeypatch, db_session: Session
) -> None:
    now = datetime.now(UTC)
    integration = GoogleDriveIntegration(google_settings(), db_session)
    db_session.add(
        GoogleDriveConnection(
            principal_id="ark",
            refresh_token_encrypted=integration._encrypt("refresh"),
            granted_scopes="https://www.googleapis.com/auth/drive.metadata.readonly",
            catalog_generation="generation",
            root_folder_id="opaque-root-id",
            created_at=now,
            updated_at=now,
        )
    )
    db_session.add(
        GoogleDriveCatalogSync(
            principal_id="ark",
            change_page_token="token",
            attempt_id="stale-attempt",
            status="syncing",
            mode="incremental",
            phase="fetching",
            last_started_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    db_session.add(
        GoogleDriveSyncAttempt(
            id="stale-attempt",
            principal_id="ark",
            mode="incremental",
            status="running",
            phase="fetching",
            started_at=now,
        )
    )
    db_session.commit()

    try:
        integration.sync_catalog("ark")
    except ActiveGoogleDriveSyncError:
        pass
    else:
        raise AssertionError("A current synchronization should be rejected")

    sync = db_session.get(GoogleDriveCatalogSync, "ark")
    assert sync is not None
    sync.last_started_at = now - timedelta(hours=1)
    db_session.commit()
    responses = iter([{"access_token": "access"}, {"changes": [], "newStartPageToken": "next"}])
    monkeypatch.setattr(
        "app.integrations.google_drive.urlopen",
        lambda *_args, **_kwargs: FakeResponse(next(responses)),
    )

    result = integration.sync_catalog("ark")

    stale_attempt = db_session.get(GoogleDriveSyncAttempt, "stale-attempt")
    assert stale_attempt is not None and stale_attempt.status == "failed"
    assert result.state == "ready"
    assert result.mode == "recovery"
    assert result.recovery is True
