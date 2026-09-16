from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app

client = TestClient(app)


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
