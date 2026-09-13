from typing import Literal

from pydantic import BaseModel

from app.core.database import DatabaseState


class HealthResponse(BaseModel):
    status: Literal["healthy", "unhealthy"]
    service: str
    database: DatabaseState
