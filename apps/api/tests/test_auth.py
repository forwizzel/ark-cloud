from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_login_creates_an_authenticated_session() -> None:
    response = client.post("/auth/login", json={"username": "ark", "password": "test-password"})

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["csrf_token"]
    assert "ark_session" in response.cookies


def test_login_rejects_invalid_credentials() -> None:
    response = client.post("/auth/login", json={"username": "ark", "password": "wrong"})

    assert response.status_code == 401


def test_logout_requires_csrf_token() -> None:
    client.post("/auth/login", json={"username": "ark", "password": "test-password"})

    response = client.post("/auth/logout")

    assert response.status_code == 403
