from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CatalogState = Literal["not_configured", "not_synced", "syncing", "ready", "error"]


class DriveCatalogStatus(BaseModel):
    state: CatalogState
    item_count: int = Field(default=0, ge=0)
    last_synced_at: datetime | None = None
    message: str


class SearchResult(BaseModel):
    source: Literal["google_drive"] = "google_drive"
    id: str
    name: str
    mime_type: str
    size_bytes: int | None = Field(default=None, ge=0)
    modified_at: datetime
    web_url: str


class SearchResponse(BaseModel):
    items: list[SearchResult] = Field(default_factory=list)
    next_cursor: str | None = None
    catalog: DriveCatalogStatus
