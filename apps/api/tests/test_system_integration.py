from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.integrations.system import SystemIntegration


@pytest.mark.parametrize(
    ("hostname", "os_name", "expected_hostname", "expected_os"),
    [
        ("backup-node", "Ubuntu 24.04 LTS", "backup-node", "Ubuntu 24.04 LTS"),
        ("nas", "Debian GNU/Linux", "nas", "Debian GNU/Linux"),
        ("", "", "API runtime", "Linux"),
    ],
)
def test_system_summary_normalizes_psutil_metrics(
    monkeypatch, hostname, os_name, expected_hostname, expected_os
) -> None:
    monkeypatch.setattr(
        "app.integrations.system.psutil.virtual_memory",
        lambda: SimpleNamespace(total=1_000, available=400, percent=60.0),
    )
    monkeypatch.setattr(
        "app.integrations.system.psutil.disk_usage",
        lambda _: SimpleNamespace(total=2_000, used=500, free=1_500, percent=25.0),
    )
    monkeypatch.setattr("app.integrations.system.psutil.cpu_percent", lambda interval: 12.5)
    monkeypatch.setattr("app.integrations.system.psutil.cpu_count", lambda: 8)
    monkeypatch.setattr("app.integrations.system.psutil.boot_time", lambda: 900.0)
    monkeypatch.setattr("app.integrations.system.time", lambda: 1_000.0)
    monkeypatch.setattr("app.integrations.system.release", lambda: "6.18-test")
    settings = Settings(
        database_url="sqlite://",
        system_hostname=hostname,
        system_os_name=os_name,
        system_storage_path="/data",
    )

    integration = SystemIntegration(settings)
    summary = integration.summary()

    assert summary.hostname == expected_hostname
    assert summary.os == expected_os
    assert summary.kernel == "6.18-test"
    assert summary.uptime_seconds == 100
    assert summary.cpu_percent == 12.5
    assert summary.cpu_count == 8
    assert summary.memory.used_bytes == 600
    assert summary.storage.available_bytes == 1_500
    assert summary.scope == "api-runtime-view"
    assert integration.health_for(summary).state == "healthy"
    assert integration.health_for(summary).name == "System metrics"
    information = integration.information()
    assert information.identity.hostname == expected_hostname
    assert information.identity.os == expected_os
    assert information.identity.kernel == "6.18-test"


def test_system_health_degrades_when_storage_is_nearly_full(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.integrations.system.psutil.virtual_memory",
        lambda: SimpleNamespace(total=1_000, available=500, percent=50.0),
    )
    monkeypatch.setattr(
        "app.integrations.system.psutil.disk_usage",
        lambda _: SimpleNamespace(total=1_000, used=950, free=50, percent=95.0),
    )
    monkeypatch.setattr("app.integrations.system.psutil.cpu_percent", lambda interval: 1.0)
    monkeypatch.setattr("app.integrations.system.psutil.cpu_count", lambda: 4)
    monkeypatch.setattr("app.integrations.system.psutil.boot_time", lambda: 0.0)

    integration = SystemIntegration(Settings(database_url="sqlite://"))

    assert integration.health_for(integration.summary()).state == "degraded"
