import json

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.google_drive import GoogleDriveIntegration


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
