from types import SimpleNamespace

import psutil
from fastapi.testclient import TestClient

from app.auth.service import Principal
from app.core.config import Settings
from app.dependencies import get_system_integration, require_principal
from app.integrations.system import SystemIntegration, _detected_gpus
from app.main import app

client = TestClient(app)


def test_information_keeps_partial_sections_and_sources(monkeypatch) -> None:
    monkeypatch.setattr("app.integrations.system.psutil.cpu_count", lambda: 4)
    monkeypatch.setattr("app.integrations.system.psutil.cpu_percent", lambda interval: 12.0)
    monkeypatch.setattr("app.integrations.system.psutil.cpu_freq", lambda: None)
    monkeypatch.setattr(
        "app.integrations.system.psutil.virtual_memory",
        lambda: SimpleNamespace(
            total=1000,
            available=600,
            percent=40,
        ),
    )
    monkeypatch.setattr(
        "app.integrations.system.psutil.swap_memory",
        lambda: SimpleNamespace(
            total=100,
            used=10,
            free=90,
            percent=10,
        ),
    )
    monkeypatch.setattr(
        "app.integrations.system.psutil.disk_usage",
        lambda _: SimpleNamespace(
            total=2000,
            used=500,
            free=1500,
            percent=25,
        ),
    )
    monkeypatch.setattr("app.integrations.system.psutil.disk_partitions", lambda all: [])
    monkeypatch.setattr("app.integrations.system.psutil.sensors_temperatures", lambda: {})
    integration = SystemIntegration(Settings(database_url="sqlite://", system_storage_path="/"))

    payload = integration.information()

    assert payload.scope == "api-runtime-view"
    assert payload.identity.source == "configured"
    assert payload.compute.source == "kernel_view"
    assert payload.memory.usage.used_bytes == 400
    assert payload.storage.usage.total_bytes == 2000
    assert payload.storage.availability == "partial"
    assert payload.sensors.availability == "unavailable"
    assert payload.sensors.warning


def test_information_survives_inaccessible_optional_metrics(monkeypatch) -> None:
    def denied(*args, **kwargs):
        raise psutil.AccessDenied()

    monkeypatch.setattr("app.integrations.system.psutil.virtual_memory", denied)
    monkeypatch.setattr("app.integrations.system.psutil.swap_memory", denied)
    monkeypatch.setattr("app.integrations.system.psutil.disk_usage", denied)
    monkeypatch.setattr("app.integrations.system.psutil.disk_partitions", denied)
    monkeypatch.setattr("app.integrations.system.psutil.sensors_temperatures", denied)
    integration = SystemIntegration(Settings(database_url="sqlite://"))

    payload = integration.information()

    assert payload.memory.availability == "unavailable"
    assert payload.storage.availability == "unavailable"
    assert payload.sensors.availability == "unavailable"
    assert payload.identity.hostname


def test_temperatures_have_clear_labels_and_retain_source_identifiers(monkeypatch) -> None:
    readings = {
        "acpitz": [SimpleNamespace(label="temp1", current=38.5)],
        "jc42": [SimpleNamespace(label="", current=47.0)],
        "coretemp": [SimpleNamespace(label="Package id 0", current=53.0)],
        "asusec": [
            SimpleNamespace(label="Chipset", current=41.0),
            SimpleNamespace(label="CPU", current=42.0),
            SimpleNamespace(label="Motherboard", current=36.0),
            SimpleNamespace(label="T_Sensor", current=32.0),
            SimpleNamespace(label="VRM", current=40.0),
        ],
        "mystery": [SimpleNamespace(label="zone9", current=31.0)],
    }
    monkeypatch.setattr("app.integrations.system.psutil.sensors_temperatures", lambda: readings)
    monkeypatch.setattr("app.integrations.system._detected_gpus", lambda: [])

    sensors = SystemIntegration(Settings(database_url="sqlite://")).information().sensors

    assert [sensor.label for sensor in sensors.temperatures] == [
        "ACPI thermal zone 1",
        "Memory module 1",
        "CPU package 0",
        "Motherboard chipset",
        "Motherboard CPU sensor",
        "Motherboard sensor",
        "External sensor header",
        "Voltage regulator (VRM)",
        "Other temperature sensor",
    ]
    assert [sensor.source_name for sensor in sensors.temperatures] == [
        "acpitz / temp1",
        "jc42",
        "coretemp / Package id 0",
        "asusec / Chipset",
        "asusec / CPU",
        "asusec / Motherboard",
        "asusec / T_Sensor",
        "asusec / VRM",
        "mystery / zone9",
    ]
    assert sensors.warning and "placement" in sensors.warning


def test_gpu_discovery_uses_visible_driver_model_and_pci_fallback(monkeypatch, tmp_path) -> None:
    drm = tmp_path / "drm"
    card = drm / "card1" / "device"
    card.mkdir(parents=True)
    (card / "vendor").write_text("0x10de\n")
    (card / "device").write_text("0x2484\n")
    (card / "uevent").write_text("PCI_SLOT_NAME=0000:01:00.0\n")
    (drm / "card1-HDMI-A-1").mkdir()
    amd = drm / "card2" / "device"
    amd.mkdir(parents=True)
    (amd / "vendor").write_text("0x1002\n")
    (amd / "device").write_text("0x1636\n")
    nvidia = tmp_path / "nvidia" / "0000:01:00.0"
    nvidia.mkdir(parents=True)
    (nvidia / "information").write_text("Model: NVIDIA GeForce RTX 3070\n")
    monkeypatch.setattr("app.integrations.system._DRM_ROOT", drm)
    monkeypatch.setattr("app.integrations.system._NVIDIA_GPU_ROOT", tmp_path / "nvidia")

    assert _detected_gpus() == ["NVIDIA GeForce RTX 3070", "AMD GPU (PCI 1002:1636)"]

    (nvidia / "information").unlink()
    assert _detected_gpus()[0] == "NVIDIA GPU (PCI 10de:2484)"
    monkeypatch.setattr("app.integrations.system._DRM_ROOT", tmp_path / "missing")
    assert _detected_gpus() == []


def test_new_system_routes_require_auth_and_validate_parameters() -> None:
    assert client.get("/system/information").status_code == 401
    app.dependency_overrides[require_principal] = lambda: Principal("ark", "ark", "test")
    integration = SystemIntegration(Settings(database_url="sqlite://"))
    app.dependency_overrides[get_system_integration] = lambda: integration

    info = client.get("/system/information")
    assert info.status_code == 200
    assert info.json()["scope"] == "api-runtime-view"
    assert client.get("/system/processes").status_code == 404
