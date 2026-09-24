from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.search import DriveCatalogStatus, DriveParentSummary, SearchResult

DriveView = Literal["all", "recent", "starred"]
DriveKind = Literal["all", "folder", "document", "image", "video", "audio", "archive", "other"]
DriveSort = Literal["modified", "created", "name", "size"]
DriveDirection = Literal["asc", "desc"]


class DriveItemsResponse(BaseModel):
    items: list[SearchResult] = Field(default_factory=list)
    next_cursor: str | None = None
    catalog: DriveCatalogStatus


class DriveFolder(BaseModel):
    id: str
    name: str
    web_url: str
    modified_at: datetime | None = None
    starred: bool = False
    breadcrumbs: list[DriveParentSummary] = Field(default_factory=list)
    breadcrumbs_complete: bool = True


class SavedSearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, max_length=200)
    view: DriveView = "all"
    kind: DriveKind = "all"
    parent_id: str | None = Field(default=None, min_length=1, max_length=256)
    modified_after: AwareDatetime | None = None
    modified_before: AwareDatetime | None = None
    min_size: int | None = Field(default=None, ge=0)
    max_size: int | None = Field(default=None, ge=0)
    starred: bool | None = None
    ownership: Literal["owned_by_me"] = "owned_by_me"
    sort: DriveSort = "modified"
    direction: DriveDirection = "desc"

    @field_validator("q")
    @classmethod
    def normalize_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value

    @model_validator(mode="after")
    def validate_ranges(self) -> SavedSearchFilters:
        if (
            self.modified_after
            and self.modified_before
            and self.modified_after >= self.modified_before
        ):
            raise ValueError("modified_after must be before modified_before")
        if (
            self.min_size is not None
            and self.max_size is not None
            and self.min_size > self.max_size
        ):
            raise ValueError("min_size must not exceed max_size")
        return self


class SavedSearchCreate(SavedSearchFilters):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class SavedSearch(BaseModel):
    id: str
    name: str
    filters: SavedSearchFilters
    created_at: datetime


class SavedSearchList(BaseModel):
    items: list[SavedSearch] = Field(default_factory=list)


class PinnedLocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drive_folder_id: str = Field(min_length=1, max_length=256)
    label: str | None = Field(default=None, max_length=100)

    @field_validator("drive_folder_id", "label")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class PinnedLocation(BaseModel):
    id: str
    drive_folder_id: str
    label: str | None = None
    folder_name: str | None = None
    available: bool
    web_url: str | None = None
    created_at: datetime


class PinnedLocationList(BaseModel):
    items: list[PinnedLocation] = Field(default_factory=list)


class KindInsight(BaseModel):
    kind: Literal["folder", "document", "image", "video", "audio", "archive", "other"]
    item_count: int = Field(ge=0)
    known_size_bytes: int = Field(ge=0)
    unknown_size_count: int = Field(ge=0)


class InsightFile(BaseModel):
    id: str
    name: str
    kind: Literal["document", "image", "video", "audio", "archive", "other"]
    size_bytes: int | None = Field(default=None, ge=0)
    modified_at: datetime
    web_url: str


class DriveInsights(BaseModel):
    account_used_bytes: int | None = Field(default=None, ge=0)
    account_total_bytes: int | None = Field(default=None, ge=0)
    catalog_known_size_bytes: int = Field(ge=0)
    catalog_unknown_size_count: int = Field(ge=0)
    by_kind: list[KindInsight] = Field(default_factory=list)
    largest_files: list[InsightFile] = Field(default_factory=list)
    stale_files: list[InsightFile] = Field(default_factory=list)
    freshness_at: datetime | None = None


class SyncAttempt(BaseModel):
    id: str
    mode: Literal["full", "incremental", "recovery"]
    status: Literal["running", "success", "failed"]
    phase: Literal["starting", "fetching", "applying", "completed", "failed"]
    processed_count: int = Field(ge=0)
    total_count: int | None = Field(default=None, ge=0)
    retryable: bool
    recovery: bool
    error: str | None = None
    started_at: datetime
    completed_at: datetime | None = None


class SyncAttemptList(BaseModel):
    items: list[SyncAttempt] = Field(default_factory=list)


class DriveActivityEvent(BaseModel):
    id: str
    event_type: Literal["created", "modified", "removed", "sync_completed", "sync_failed"]
    file_id: str | None = None
    name: str | None = None
    kind: Literal["folder", "document", "image", "video", "audio", "archive", "other"] | None = None
    summary: str
    observed_at: datetime


class DriveActivityResponse(BaseModel):
    items: list[DriveActivityEvent] = Field(default_factory=list)
    next_cursor: str | None = None
    scope: Literal["sync_observed"] = "sync_observed"
    message: str = (
        "Activity reflects metadata observed during synchronization, not a full audit log."
    )
