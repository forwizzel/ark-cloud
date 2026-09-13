import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from http.client import HTTPException as HTTPClientError
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.core.config import Settings
from app.core.logging import get_logger
from app.integrations.base import Integration
from app.schemas.integrations import IntegrationHealth, TailscaleDevice, TailscaleSummary

ResponseOpener = Callable[..., Any]
TAILSCALE_API_ORIGIN = "https://api.tailscale.com"


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _open_request(request: Request, timeout: int):
    return build_opener(_NoRedirectHandler()).open(request, timeout=timeout)


class TailscaleIntegration(Integration):
    integration_id = "tailscale"
    name = "Tailscale"
    _online_window = timedelta(minutes=5)
    _response_limit = 2_000_000

    def __init__(
        self,
        settings: Settings,
        opener: ResponseOpener = _open_request,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._api_key = settings.tailscale_api_key
        self._tailnet = settings.tailscale_tailnet
        self._opener = opener
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._api_key.get_secret_value())

    def summary(self) -> TailscaleSummary:
        collected_at = self._clock()
        if not self.configured:
            return TailscaleSummary(
                state="not_configured",
                message="Add a Tailscale access token to enable device status.",
                collected_at=collected_at,
            )

        try:
            devices = self._fetch_devices(collected_at)
        except HTTPError as error:
            message = f"Tailscale API returned HTTP {error.code}."
            get_logger(__name__).warning(
                "tailscale_request_failed",
                extra={"integration": self.integration_id, "status_code": error.code},
            )
            return TailscaleSummary(state="unavailable", message=message, collected_at=collected_at)
        except OSError, HTTPClientError:
            get_logger(__name__).warning(
                "tailscale_request_failed",
                extra={"integration": self.integration_id, "reason": "unreachable"},
            )
            return TailscaleSummary(
                state="unavailable",
                message="Tailscale API is unreachable.",
                collected_at=collected_at,
            )
        except json.JSONDecodeError, KeyError, TypeError, ValueError:
            get_logger(__name__).warning(
                "tailscale_response_invalid",
                extra={"integration": self.integration_id},
            )
            return TailscaleSummary(
                state="unavailable",
                message="Tailscale API returned invalid data.",
                collected_at=collected_at,
            )

        return TailscaleSummary(
            state="healthy",
            device_count=len(devices),
            online_count=sum(device.online for device in devices),
            devices=devices,
            message="Device status is current.",
            collected_at=collected_at,
        )

    def health_for(self, summary: TailscaleSummary) -> IntegrationHealth:
        return IntegrationHealth(
            id=self.integration_id,
            name=self.name,
            state=summary.state,
            message=summary.message,
            checked_at=summary.collected_at,
        )

    def health(self) -> IntegrationHealth:
        return self.health_for(self.summary())

    def _fetch_devices(self, collected_at: datetime) -> list[TailscaleDevice]:
        tailnet = quote(self._tailnet, safe="")
        request = Request(
            f"{TAILSCALE_API_ORIGIN}/api/v2/tailnet/{tailnet}/devices",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key.get_secret_value()}",  # type: ignore[union-attr]
                "User-Agent": "ark-cloud/0.1",
            },
            method="GET",
        )
        with self._opener(request, timeout=5) as response:
            body = response.read(self._response_limit + 1)
        if len(body) > self._response_limit:
            raise ValueError("Tailscale response exceeded the size limit")

        payload = json.loads(body)
        raw_devices = payload["devices"]
        if not isinstance(raw_devices, list):
            raise TypeError("devices must be a list")
        if not all(isinstance(device, dict) for device in raw_devices):
            raise TypeError("each device must be an object")
        return [self._normalize_device(device, collected_at) for device in raw_devices]

    def _normalize_device(
        self, raw_device: dict[str, Any], collected_at: datetime
    ) -> TailscaleDevice:
        last_seen = _parse_datetime(raw_device.get("lastSeen"))
        connected = raw_device.get("connectedToControl")
        if isinstance(connected, bool):
            online = connected
        else:
            age = collected_at - last_seen if last_seen else None
            online = bool(age is not None and timedelta(0) <= age <= self._online_window)
        return TailscaleDevice(
            id=str(raw_device["id"]),
            hostname=str(raw_device.get("hostname") or "Unknown"),
            os=str(raw_device.get("os") or "Unknown"),
            addresses=[str(address) for address in raw_device.get("addresses", [])],
            online=online,
            last_seen=last_seen,
        )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
