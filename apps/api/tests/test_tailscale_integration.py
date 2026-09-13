import json
from datetime import UTC, datetime, timedelta
from urllib.error import URLError

from app.core.config import Settings
from app.integrations.tailscale import TailscaleIntegration, _NoRedirectHandler


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._body


def test_tailscale_summary_normalizes_devices() -> None:
    now = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    captured_request = None

    def opener(request, timeout: int):
        nonlocal captured_request
        captured_request = request
        assert timeout == 5
        return FakeResponse(
            {
                "devices": [
                    {
                        "id": "device-1",
                        "name": "ark.example.ts.net",
                        "hostname": "ark",
                        "os": "linux",
                        "addresses": ["100.64.0.1"],
                        "connectedToControl": True,
                        "tags": ["tag:server"],
                    },
                    {
                        "id": "device-2",
                        "hostname": "laptop",
                        "os": "windows",
                        "addresses": ["100.64.0.2"],
                        "connectedToControl": False,
                        "lastSeen": (now - timedelta(hours=1)).isoformat(),
                    },
                    {
                        "id": "device-3",
                        "hostname": "clock-skewed",
                        "os": "linux",
                        "addresses": [],
                        "lastSeen": (now + timedelta(minutes=1)).isoformat(),
                    },
                ]
            }
        )

    settings = Settings(database_url="sqlite://", tailscale_api_key="test-token")
    integration = TailscaleIntegration(settings, opener=opener, clock=lambda: now)

    summary = integration.summary()

    assert summary.state == "healthy"
    assert summary.device_count == 3
    assert summary.online_count == 1
    assert summary.devices[0].online is True
    assert summary.devices[1].online is False
    assert summary.devices[2].online is False
    assert captured_request.get_header("Authorization") == "Bearer test-token"
    assert captured_request.get_method() == "GET"
    assert captured_request.full_url.endswith("/api/v2/tailnet/-/devices")


def test_tailscale_is_optional() -> None:
    integration = TailscaleIntegration(Settings(database_url="sqlite://"))

    summary = integration.summary()

    assert summary.state == "not_configured"
    assert summary.devices == []


def test_tailscale_network_failure_is_normalized() -> None:
    def unavailable(*_args, **_kwargs):
        raise URLError("not reachable")

    settings = Settings(database_url="sqlite://", tailscale_api_key="test-token")
    integration = TailscaleIntegration(settings, opener=unavailable)

    summary = integration.summary()

    assert summary.state == "unavailable"
    assert summary.message == "Tailscale API is unreachable."


def test_tailscale_redirects_are_refused() -> None:
    handler = _NoRedirectHandler()

    redirect = handler.redirect_request(
        None,
        None,
        302,
        "Found",
        {},
        "https://example.com/collect",
    )

    assert redirect is None
