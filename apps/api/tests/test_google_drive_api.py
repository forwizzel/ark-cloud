import json
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.dependencies import get_google_drive_integration
from app.integrations.google_drive import ActiveGoogleDriveSyncError
from app.main import app
from app.schemas.search import DriveCatalogStatus

client = TestClient(app)


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
        session_secret="test-session-secret",
        google_client_id="google-client-id",
        google_client_secret="google-client-secret",
        google_redirect_uri="http://127.0.0.1:5173/api/integrations/google-drive/oauth/callback",
        google_token_encryption_key=Fernet.generate_key().decode(),
    )


def login() -> None:
    response = client.post("/auth/login", json={"username": "ark", "password": "test-password"})

    assert response.status_code == 200


def test_connect_redirects_to_google_with_a_state_value() -> None:
    login()
    app.dependency_overrides[get_settings] = google_settings

    response = client.get("/integrations/google-drive/connect", follow_redirects=False)

    assert response.status_code == 302
    redirect = urlparse(response.headers["location"])
    query = parse_qs(redirect.query)
    assert redirect.scheme == "https"
    assert redirect.netloc == "accounts.google.com"
    assert query["client_id"] == ["google-client-id"]
    assert query["redirect_uri"] == [google_settings().google_redirect_uri]
    assert query["scope"] == ["https://www.googleapis.com/auth/drive.metadata.readonly"]
    assert len(query["state"][0]) >= 32


def test_callback_rejects_an_invalid_state() -> None:
    login()
    app.dependency_overrides[get_settings] = google_settings

    response = client.get(
        "/integrations/google-drive/oauth/callback?code=authorization-code&state=invalid",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?google_drive=invalid_state"


def test_callback_connects_drive_and_builds_catalog(monkeypatch) -> None:
    login()
    app.dependency_overrides[get_settings] = google_settings
    connect_response = client.get("/integrations/google-drive/connect", follow_redirects=False)
    state = parse_qs(urlparse(connect_response.headers["location"]).query)["state"][0]
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
            {"files": []},
            {"changes": [], "newStartPageToken": "changes-2"},
        ]
    )
    monkeypatch.setattr(
        "app.integrations.google_drive.urlopen",
        lambda *_args, **_kwargs: FakeResponse(next(responses)),
    )

    response = client.get(
        "/integrations/google-drive/oauth/callback",
        params={"code": "authorization-code", "state": state},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?google_drive=connected"
    status_response = client.get("/integrations/google-drive/catalog/status")
    assert status_response.json()["state"] == "ready"


class FakeCatalogIntegration:
    def sync_catalog(self, _: str) -> DriveCatalogStatus:
        return DriveCatalogStatus(
            state="ready",
            item_count=3,
            message="The Drive catalog is current.",
        )


def test_manual_catalog_sync_requires_csrf() -> None:
    session = client.post(
        "/auth/login", json={"username": "ark", "password": "test-password"}
    ).json()
    app.dependency_overrides[get_google_drive_integration] = lambda: FakeCatalogIntegration()

    rejected = client.post("/integrations/google-drive/catalog/sync")
    response = client.post(
        "/integrations/google-drive/catalog/sync",
        headers={"X-CSRF-Token": session["csrf_token"]},
    )

    assert rejected.status_code == 403
    assert response.status_code == 200
    assert response.json()["item_count"] == 3


class ActiveCatalogIntegration:
    def sync_catalog(self, _: str) -> DriveCatalogStatus:
        raise ActiveGoogleDriveSyncError("A Drive catalog synchronization is already in progress.")


def test_manual_catalog_sync_maps_active_attempt_to_conflict() -> None:
    session = client.post(
        "/auth/login", json={"username": "ark", "password": "test-password"}
    ).json()
    app.dependency_overrides[get_google_drive_integration] = lambda: ActiveCatalogIntegration()

    response = client.post(
        "/integrations/google-drive/catalog/sync",
        headers={"X-CSRF-Token": session["csrf_token"]},
    )

    assert response.status_code == 409
