from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.integrations import ResourceUsage

Availability = Literal["available", "partial", "unavailable"]
Source = Literal["configured", "runtime", "kernel_view", "filesystem"]


class Section(BaseModel):
    availability: Availability
    source: Source
    warning: str | None = None


class Identity(Section):
    hostname: str
    os: str
    kernel: str | None = None
    architecture: str | None = None
    python_version: str
    api_version: str
    host_uptime_seconds: int | None = Field(default=None, ge=0)


class Compute(Section):
    model: str | None = None
    gpus: list[str] = Field(default_factory=list)
    logical_cores: int | None = Field(default=None, ge=1)
    percent: float | None = Field(default=None, ge=0, le=100)
    load_average: tuple[float, float, float] | None = None
    frequency_mhz: float | None = Field(default=None, ge=0)


class Memory(Section):
    usage: ResourceUsage | None = None
    swap: ResourceUsage | None = None


class Storage(Section):
    path: str
    usage: ResourceUsage | None = None
    filesystem_type: str | None = None


class Temperature(BaseModel):
    label: str
    source_name: str
    celsius: float


class Sensors(Section):
    temperatures: list[Temperature] = Field(default_factory=list)


class SystemInformation(BaseModel):
    scope: Literal["api-runtime-view"] = "api-runtime-view"
    collected_at: datetime
    identity: Identity
    compute: Compute
    memory: Memory
    storage: Storage
    sensors: Sensors
