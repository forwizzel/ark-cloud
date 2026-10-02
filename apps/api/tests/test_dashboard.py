from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.auth.service import Principal
from app.core.database import get_database_state
from app.dependencies import (
    get_system_integration,
    get_tailscale_integration,
    require_principal,
)
from app.integrations.base import IntegrationError
from app.main import app
from app.schemas.integrations import (
    IntegrationHealth,
    ResourceUsage,
    SystemSummary,
    TailscaleSummary,
)

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


class FakeSystemIntegration:
    integration_id = "system"
    name = "Ark system"

    def summary(self) -> SystemSummary:
        return SystemSummary(
            hostname="Ark",
            os="Fedora Linux",
            kernel="6.18-test",
            uptime_seconds=3600,
            cpu_percent=10,
            cpu_count=8,
            memory=ResourceUsage(
                total_bytes=1_000,
                used_bytes=500,
                available_bytes=500,
                percent=50,
            ),
            storage=ResourceUsage(
                total_bytes=2_000,
                used_bytes=500,
                available_bytes=1_500,
                percent=25,
            ),
            storage_path="/",
            collected_at=NOW,
        )

    def health_for(self, _: SystemSummary) -> IntegrationHealth:
        return IntegrationHealth(
            id=self.integration_id,
            name=self.name,
            state="healthy",
            message="System metrics are available.",
            checked_at=NOW,
        )


class FakeTailscaleIntegration:
    integration_id = "tailscale"
    name = "Tailscale"

    def summary(self) -> TailscaleSummary:
        return TailscaleSummary(
            state="not_configured",
            message="Add a Tailscale access token to enable device status.",
            collected_at=NOW,
        )

    def health_for(self, summary: TailscaleSummary) -> IntegrationHealth:
        return IntegrationHealth(
            id=self.integration_id,
            name=self.name,
            state=summary.state,
            message=summary.message,
            checked_at=summary.collected_at,
        )


class UnavailableSystemIntegration(FakeSystemIntegration):
    def summary(self) -> SystemSummary:
        raise IntegrationError("System metrics are unavailable.")


client = TestClient(app)


def test_dashboard_normalizes_platform_and_integrations() -> None:
    app.dependency_overrides[get_database_state] = lambda: "connected"
    app.dependency_overrides[get_system_integration] = lambda: FakeSystemIntegration()
    app.dependency_overrides[get_tailscale_integration] = lambda: FakeTailscaleIntegration()
    app.dependency_overrides[require_principal] = lambda: Principal("ark", "ark", "test")

    response = client.get("/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["platform"]["database"] == "connected"
    assert payload["system"]["hostname"] == "Ark"
    assert payload["system"]["cpu_percent"] == 10
    assert payload["tailscale"]["state"] == "not_configured"
    assert "google_drive" not in payload
    assert [integration["id"] for integration in payload["integrations"]] == [
        "system",
        "tailscale",
    ]


def test_dashboard_preserves_partial_results_when_system_and_database_fail() -> None:
    app.dependency_overrides[get_database_state] = lambda: "disconnected"
    app.dependency_overrides[get_system_integration] = lambda: UnavailableSystemIntegration()
    app.dependency_overrides[get_tailscale_integration] = lambda: FakeTailscaleIntegration()
    app.dependency_overrides[require_principal] = lambda: Principal("ark", "ark", "test")

    response = client.get("/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["platform"]["status"] == "unhealthy"
    assert payload["system"] is None
    assert payload["integrations"][0]["state"] == "unavailable"
    assert payload["tailscale"]["state"] == "not_configured"
