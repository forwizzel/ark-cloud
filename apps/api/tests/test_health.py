from fastapi.testclient import TestClient

from app.core.database import get_database_state
from app.main import app

client = TestClient(app)


def test_health_reports_connected_database() -> None:
    app.dependency_overrides[get_database_state] = lambda: "connected"

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "ark-cloud-api",
        "database": "connected",
    }
    app.dependency_overrides.clear()


def test_health_reports_database_failure() -> None:
    app.dependency_overrides[get_database_state] = lambda: "disconnected"

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
    assert response.json()["database"] == "disconnected"
    app.dependency_overrides.clear()
