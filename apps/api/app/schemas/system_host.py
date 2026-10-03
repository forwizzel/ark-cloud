"""Version-one host protocol. Limits also apply to trusted-agent reports."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(max_length=256)]
Percent = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0)]
Reading = Annotated[float, Field(allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServicePolicy(StrictModel):
    unit: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.@:-]+\.service$", max_length=128)]
    scope: Literal["user", "system"] = "user"
    actions: list[Literal["start", "stop", "restart"]] = Field(max_length=3)


class Policy(StrictModel):
    terminal: bool = False
    power: bool = False
    processes: bool = True
    shell: Text = ""
    account: Text = ""
    services: list[ServicePolicy] = Field(default_factory=list, max_length=32)


class Identity(StrictModel):
    hostname: Text
    os: Text
    kernel: Text
    architecture: Text
    boot_time: datetime
    uptime_seconds: Count


class Compute(StrictModel):
    model: Text | None = None
    physical_cores: int | None = None
    logical_cores: int | None = None
    sockets: int | None = None
    percent: Percent | None = None
    per_core: list[Percent] = Field(default_factory=list, max_length=1024)
    frequency_mhz: Reading | None = None
    load_average: tuple[Reading, Reading, Reading] | None = None
    gpus: list[Text] = Field(default_factory=list, max_length=16)


class Usage(StrictModel):
    total_bytes: Count
    used_bytes: Count
    available_bytes: Count
    percent: Percent


class Memory(StrictModel):
    usage: Usage | None = None
    swap: Usage | None = None
    cached_bytes: Count | None = None
    buffers_bytes: Count | None = None
    swap_in_bytes: Count | None = None
    swap_out_bytes: Count | None = None


class Temperature(StrictModel):
    id: Text
    group: Literal["cpu", "gpu", "memory", "motherboard", "storage", "other"]
    label: Text
    source_name: Text
    celsius: Reading
    high: Reading | None = None
    critical: Reading | None = None


class Mount(StrictModel):
    id: Text
    path: Annotated[str, Field(max_length=2048)]
    device: Text
    filesystem: Text
    options: Text
    usage: Usage | None = None


class DiskIO(StrictModel):
    device: Text
    read_bytes: Count
    write_bytes: Count
    read_bytes_per_second: Reading | None = None
    write_bytes_per_second: Reading | None = None


class Process(StrictModel):
    pid: Annotated[int, Field(gt=0)]
    started_at: Reading
    owner: Text
    name: Text
    percent: Percent | None = None
    memory_bytes: Count
    state: Text


class Service(StrictModel):
    unit: Text
    scope: Literal["user", "system"]
    state: Text
    actions: list[Literal["start", "stop", "restart"]] = Field(max_length=3)


class SectionAvailability(StrictModel):
    compute: Literal["available", "partial", "unavailable"] = "partial"
    memory: Literal["available", "partial", "unavailable"] = "partial"
    temperatures: Literal["available", "partial", "unavailable"] = "unavailable"
    storage: Literal["available", "partial", "unavailable"] = "unavailable"


class PublicSnapshot(StrictModel):
    version: Literal[1] = 1
    scope: Literal["host"] = "host"
    boot_id: Annotated[str, Field(max_length=64)]
    collected_at: datetime
    identity: Identity
    compute: Compute
    memory: Memory
    temperatures: list[Temperature] = Field(default_factory=list, max_length=128)
    mounts: list[Mount] = Field(default_factory=list, max_length=128)
    omitted_mounts: list[Text] = Field(default_factory=list, max_length=128)
    disk_io: list[DiskIO] = Field(default_factory=list, max_length=128)
    warnings: list[Text] = Field(default_factory=list, max_length=32)
    availability: SectionAvailability = Field(default_factory=SectionAvailability)


class Snapshot(PublicSnapshot):
    services: list[Service] = Field(default_factory=list, max_length=32)
    processes: list[Process] = Field(default_factory=list, max_length=2048)
    capabilities: Policy = Field(default_factory=Policy)


class HistorySample(StrictModel):
    collected_at: datetime
    cpu: Percent | None
    memory: Percent | None


class HostInformation(StrictModel):
    state: Literal["not_enrolled", "connected", "offline", "revoked"]
    scope: Literal["host"]
    collected_at: datetime | None
    snapshot: PublicSnapshot | None
    capabilities: dict[str, bool]
    history: list[HistorySample] = Field(max_length=120)


class HostStatus(StrictModel):
    state: Literal["not_enrolled", "connected", "offline", "revoked"]
    scope: Literal["host"]
    collected_at: datetime | None
    policy: Policy | None


class ServiceList(StrictModel):
    items: list[Service]


class ProcessList(StrictModel):
    items: list[Process]
    total: int


class ServiceAction(StrictModel):
    action: Literal["service"]
    unit: Text
    scope: Literal["user", "system"]
    operation: Literal["start", "stop", "restart"]


class ProcessAction(StrictModel):
    action: Literal["terminate"]
    pid: Annotated[int, Field(gt=0)]
    started_at: Reading


class PowerAction(StrictModel):
    action: Literal["restart", "shutdown"]


class JobRequest(StrictModel):
    idempotency_key: Annotated[str, Field(min_length=16, max_length=128)]
    payload: Annotated[ServiceAction | ProcessAction | PowerAction, Field(discriminator="action")]
