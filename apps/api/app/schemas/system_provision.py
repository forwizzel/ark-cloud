from typing import Annotated, Literal

from pydantic import Field

from app.schemas.system_host import ServicePolicy, StrictModel, Text


class Configuration(StrictModel):
    terminal: bool = True
    processes: bool = True
    power: bool = False
    shell: Text = ""
    services: list[ServicePolicy] = Field(default_factory=list, max_length=32)


class Inventory(StrictModel):
    supported: bool = True
    account: Text
    default_shell: Text
    shells: list[Text] = Field(max_length=32)
    services: list[ServicePolicy] = Field(max_length=128)
    power: bool = False
    message: Text = ""


class Operation(StrictModel):
    action: Literal["connect", "disconnect"]
    configuration: Configuration | None = None
    idempotency_key: Annotated[str, Field(min_length=16, max_length=128)]


class Report(StrictModel):
    inventory: Inventory
    job_id: Annotated[str, Field(max_length=36)] | None = None
    state: Literal["applying", "verifying", "completed", "failed"] | None = None
    message: Annotated[str, Field(max_length=500)] = ""
