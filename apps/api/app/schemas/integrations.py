from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.health import HealthResponse

IntegrationState = Literal["healthy", "degraded", "unavailable", "not_configured"]


class IntegrationHealth(BaseModel):
    id: str
    name: str
    state: IntegrationState
    message: str
    checked_at: datetime


class ResourceUsage(BaseModel):
    total_bytes: int = Field(ge=0)
    used_bytes: int = Field(ge=0)
    available_bytes: int = Field(ge=0)
    percent: float = Field(ge=0, le=100)


class SystemSummary(BaseModel):
    hostname: str
    os: str
    kernel: str
    uptime_seconds: int = Field(ge=0)
    cpu_percent: float = Field(ge=0, le=100)
    cpu_count: int = Field(ge=1)
    memory: ResourceUsage
    storage: ResourceUsage
    storage_path: str
    scope: Literal["api-runtime-view"] = "api-runtime-view"
    collected_at: datetime


class TailscaleDevice(BaseModel):
    id: str
    hostname: str
    os: str
    addresses: list[str]
    online: bool
    last_seen: datetime | None


class TailscaleSummary(BaseModel):
    state: IntegrationState
    device_count: int = 0
    online_count: int = 0
    devices: list[TailscaleDevice] = Field(default_factory=list)
    message: str
    collected_at: datetime


class GoogleDriveSummary(BaseModel):
    state: IntegrationState
    account_email: str | None = None
    account_name: str | None = None
    used_bytes: int | None = Field(default=None, ge=0)
    total_bytes: int | None = Field(default=None, ge=0)
    available_bytes: int | None = Field(default=None, ge=0)
    percent: float | None = Field(default=None, ge=0, le=100)
    message: str
    checked_at: datetime
    web_url: str = "https://drive.google.com/"


class DashboardResponse(BaseModel):
    platform: HealthResponse
    system: SystemSummary | None
    tailscale: TailscaleSummary
    google_drive: GoogleDriveSummary
    integrations: list[IntegrationHealth]
    generated_at: datetime
