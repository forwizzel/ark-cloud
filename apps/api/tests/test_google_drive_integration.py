import json
from datetime import UTC, datetime

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.google_drive import GoogleDriveError, GoogleDriveIntegration
from app.models import GoogleDriveCatalogItem


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
                        "parents": ["root"],
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
                            "parents": ["root"],
                            "trashed": False,
                            "ownedByMe": True,
                        },
                    }
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
