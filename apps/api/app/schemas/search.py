from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CatalogState = Literal["not_configured", "not_synced", "syncing", "ready", "error"]


class DriveCatalogStatus(BaseModel):
    state: CatalogState
    item_count: int = Field(default=0, ge=0)
    last_synced_at: datetime | None = None
    revision: int = Field(default=0, ge=0)
    last_started_at: datetime | None = None
    mode: Literal["full", "incremental", "recovery"] | None = None
    phase: Literal["starting", "fetching", "applying", "completed", "failed"] | None = None
    processed_count: int = Field(default=0, ge=0)
    total_count: int | None = Field(default=None, ge=0)
    retryable: bool = False
    recovery: bool = False
    message: str


class SearchResult(BaseModel):
    source: Literal["google_drive"] = "google_drive"
    id: str
    name: str
    mime_type: str
    size_bytes: int | None = Field(default=None, ge=0)
    kind: Literal["folder", "document", "image", "video", "audio", "archive", "other"] = "other"
    created_at: datetime | None = None
    modified_at: datetime
    starred: bool = False
    ownership: Literal["owned_by_me"] = "owned_by_me"
    parent: DriveParentSummary | None = None
    status_labels: list[str] = Field(default_factory=list)
    web_url: str


class SearchResponse(BaseModel):
    items: list[SearchResult] = Field(default_factory=list)
    next_cursor: str | None = None
    catalog: DriveCatalogStatus


class DriveParentSummary(BaseModel):
    id: str
    name: str
    available: bool = True
