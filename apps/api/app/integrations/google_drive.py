import json
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.client import HTTPException as HTTPClientError
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.base import Integration
from app.models import (
    GoogleDriveActivity,
    GoogleDriveCatalogItem,
    GoogleDriveCatalogSync,
    GoogleDriveConnection,
    GoogleDriveParentEdge,
    GoogleDrivePinnedLocation,
    GoogleDriveSavedSearch,
    GoogleDriveSyncAttempt,
)
from app.schemas.integrations import GoogleDriveSummary, IntegrationHealth
from app.schemas.search import DriveCatalogStatus
from app.services.drive_workspace import drive_kind

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ABOUT_URL = "https://www.googleapis.com/drive/v3/about"
GOOGLE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
GOOGLE_CHANGES_URL = "https://www.googleapis.com/drive/v3/changes"
GOOGLE_START_PAGE_TOKEN_URL = "https://www.googleapis.com/drive/v3/changes/startPageToken"
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.metadata.readonly"
GOOGLE_FILE_FIELDS = (
    "id,name,mimeType,size,createdTime,modifiedTime,parents,trashed,ownedByMe,starred"
)


@dataclass(frozen=True)
class _CatalogRecord:
    file_id: str
    name: str
    mime_type: str
    size_bytes: int | None
    created_at: datetime | None
    modified_at: datetime
    parent_ids: list[str]
    starred: bool
    owned_by_me: bool


class GoogleDriveError(RuntimeError):
    """A safe, normalized Google Drive error."""


class ActiveGoogleDriveSyncError(GoogleDriveError):
    """Raised when another non-stale synchronization owns the catalog."""


class _ExpiredChangeTokenError(GoogleDriveError):
    """The Drive changes cursor is no longer valid."""


class GoogleDriveIntegration(Integration):
    integration_id = "google_drive"
    name = "Google Drive"
    _catalog_page_limit = 100
    _catalog_sync_time_limit_seconds = 30
    _active_sync_timeout = timedelta(minutes=15)
    _activity_retention = 500
    _attempt_retention = 100

    def __init__(self, settings: Settings, db: Session) -> None:
        self._settings = settings
        self._db = db

    def summary(self, principal_id: str, force_refresh: bool = False) -> GoogleDriveSummary:
        timestamp = datetime.now(UTC)
        if not self._settings.google_is_configured:
            return GoogleDriveSummary(
                state="not_configured",
                message="Add Google OAuth credentials to enable Drive status.",
                checked_at=timestamp,
            )

        connection = self._db.get(GoogleDriveConnection, principal_id)
        if connection is None:
            return GoogleDriveSummary(
                state="not_configured",
                message="Connect a Google Drive account to enable Drive status.",
                checked_at=timestamp,
            )

        last_checked_at = _as_utc(connection.last_checked_at)
        is_stale = last_checked_at is None or last_checked_at <= timestamp - timedelta(
            seconds=self._settings.google_status_cache_seconds
        )
        if force_refresh or is_stale:
            try:
                self._refresh(connection)
            except GoogleDriveError as error:
                connection.last_error = str(error)
                connection.last_checked_at = timestamp
                connection.updated_at = timestamp
                self._db.commit()

        return self._summary_from_connection(connection, timestamp)

    def health_for(self, summary: GoogleDriveSummary) -> IntegrationHealth:
        return IntegrationHealth(
            id=self.integration_id,
            name=self.name,
            state=summary.state,
            message=summary.message,
            checked_at=summary.checked_at,
        )

    def health(self) -> IntegrationHealth:
        return IntegrationHealth(
            id=self.integration_id,
            name=self.name,
            state="not_configured",
            message="Google Drive status requires an authenticated session.",
            checked_at=datetime.now(UTC),
        )

    def catalog_status(self, principal_id: str) -> DriveCatalogStatus:
        count = self._db.scalar(
            select(func.count())
            .select_from(GoogleDriveCatalogItem)
            .where(GoogleDriveCatalogItem.principal_id == principal_id)
        )
        if not self._settings.google_is_configured:
            return DriveCatalogStatus(
                state="not_configured",
                item_count=count or 0,
                message="Add Google OAuth credentials to enable the Drive catalog.",
            )
        connection = self._db.get(GoogleDriveConnection, principal_id)
        if connection is None:
            return DriveCatalogStatus(
                state="not_configured",
                message="Connect Google Drive to build the catalog.",
            )
        sync = self._db.get(GoogleDriveCatalogSync, principal_id)
        if sync is None:
            return DriveCatalogStatus(
                state="not_synced",
                item_count=count or 0,
                message="The Drive catalog has not been synchronized.",
            )
        messages = {
            "syncing": "Google Drive metadata is being cataloged.",
            "ready": "The Drive catalog is current.",
            "error": sync.last_error or "The Drive catalog could not be synchronized.",
        }
        state = sync.status if sync.status in messages else "error"
        return DriveCatalogStatus(
            state=state,
            item_count=count or 0,
            last_synced_at=_as_utc(sync.last_completed_at),
            revision=sync.catalog_revision,
            last_started_at=_as_utc(sync.last_started_at),
            mode=sync.mode,  # type: ignore[arg-type]
            phase=sync.phase,  # type: ignore[arg-type]
            processed_count=sync.processed_count,
            total_count=sync.total_count,
            retryable=sync.retryable,
            recovery=sync.recovery,
            message=messages[state],  # type: ignore[index]
        )

    def sync_catalog(self, principal_id: str) -> DriveCatalogStatus:
        connection, generation = self._prepare_connection(principal_id)

        timestamp = datetime.now(UTC)
        deadline = time.monotonic() + self._catalog_sync_time_limit_seconds
        attempt_id = str(uuid.uuid4())
        sync = self._begin_catalog_sync(principal_id, generation, attempt_id, timestamp)

        try:
            access_token = self._access_token(connection)
            root_folder_id = connection.root_folder_id or self._fetch_root_folder_id(access_token)
            if sync.change_page_token:
                try:
                    changes, next_token = self._fetch_changes(
                        access_token, sync.change_page_token, deadline, root_folder_id
                    )
                except _ExpiredChangeTokenError:
                    self._mark_recovery(principal_id, attempt_id)
                    records, next_token = self._fetch_full_catalog(
                        access_token, deadline, root_folder_id
                    )
                    self._mark_applying(principal_id, attempt_id, len(records))
                    completed_sync = self._lock_sync_attempt(principal_id, attempt_id)
                    completed_connection = self._lock_connection(principal_id, generation)
                    self._replace_catalog(principal_id, records, timestamp)
                    processed_count = len(records)
                    mode = "recovery"
                else:
                    self._mark_applying(principal_id, attempt_id, len(changes))
                    completed_sync = self._lock_sync_attempt(principal_id, attempt_id)
                    completed_connection = self._lock_connection(principal_id, generation)
                    self._apply_changes(principal_id, changes, timestamp)
                    processed_count = len(changes)
                    mode = sync.mode or "incremental"
            else:
                records, next_token = self._fetch_full_catalog(
                    access_token, deadline, root_folder_id
                )
                self._mark_applying(principal_id, attempt_id, len(records))
                completed_sync = self._lock_sync_attempt(principal_id, attempt_id)
                completed_connection = self._lock_connection(principal_id, generation)
                self._replace_catalog(principal_id, records, timestamp)
                processed_count = len(records)
                mode = sync.mode or "full"

            completed_at = datetime.now(UTC)
            completed_connection.root_folder_id = root_folder_id
            completed_sync.change_page_token = next_token
            completed_sync.attempt_id = None
            completed_sync.status = "ready"
            completed_sync.catalog_revision += 1
            completed_sync.mode = mode
            completed_sync.phase = "completed"
            completed_sync.processed_count = processed_count
            completed_sync.total_count = processed_count
            completed_sync.retryable = False
            completed_sync.last_completed_at = completed_at
            completed_sync.last_error = None
            completed_sync.updated_at = completed_at
            attempt = self._db.get(GoogleDriveSyncAttempt, attempt_id)
            if attempt is None:
                raise GoogleDriveError("The Drive synchronization history could not be updated.")
            attempt.mode = mode
            attempt.status = "success"
            attempt.phase = "completed"
            attempt.processed_count = processed_count
            attempt.total_count = processed_count
            attempt.retryable = False
            attempt.completed_at = completed_at
            self._add_activity(
                principal_id,
                "sync_completed",
                f"{mode.capitalize()} metadata synchronization completed "
                f"({processed_count} items observed).",
                completed_at,
            )
            self._prune_history(principal_id)
            self._db.commit()
        except (GoogleDriveError, SQLAlchemyError) as error:
            self._db.rollback()
            message = (
                str(error)
                if isinstance(error, GoogleDriveError)
                else "The Drive catalog could not be stored."
            )
            try:
                current_connection = self._db.scalar(
                    select(GoogleDriveConnection)
                    .where(GoogleDriveConnection.principal_id == principal_id)
                    .execution_options(populate_existing=True)
                )
                failed_sync = self._db.scalar(
                    select(GoogleDriveCatalogSync)
                    .where(GoogleDriveCatalogSync.principal_id == principal_id)
                    .execution_options(populate_existing=True)
                )
                if (
                    current_connection is not None
                    and current_connection.catalog_generation == generation
                    and failed_sync is not None
                    and failed_sync.attempt_id == attempt_id
                ):
                    failed_at = datetime.now(UTC)
                    retryable = _is_retryable_error(error)
                    failed_sync.status = "error"
                    failed_sync.attempt_id = None
                    failed_sync.phase = "failed"
                    failed_sync.retryable = retryable
                    failed_sync.last_error = message
                    failed_sync.updated_at = failed_at
                    attempt = self._db.get(GoogleDriveSyncAttempt, attempt_id)
                    if attempt is not None and attempt.status == "running":
                        attempt.status = "failed"
                        attempt.phase = "failed"
                        attempt.retryable = retryable
                        attempt.error = message
                        attempt.completed_at = failed_at
                    self._add_activity(
                        principal_id,
                        "sync_failed",
                        f"Metadata synchronization failed: {message}",
                        failed_at,
                    )
                    self._prune_history(principal_id)
                    self._db.commit()
            except SQLAlchemyError:
                self._db.rollback()
            raise GoogleDriveError(message) from error
        return self.catalog_status(principal_id)

    def _prepare_connection(self, principal_id: str) -> tuple[GoogleDriveConnection, str]:
        try:
            connection = self._db.scalar(
                select(GoogleDriveConnection)
                .where(GoogleDriveConnection.principal_id == principal_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if connection is None:
                raise GoogleDriveError("Connect Google Drive before synchronizing the catalog.")
            if connection.catalog_generation is None:
                connection.catalog_generation = str(uuid.uuid4())
            generation = connection.catalog_generation
            self._db.commit()
        except SQLAlchemyError as error:
            self._db.rollback()
            raise GoogleDriveError(
                "The Drive connection could not start synchronization."
            ) from error
        if generation is None:
            raise GoogleDriveError("The Drive connection could not initialize synchronization.")
        return connection, generation

    def _begin_catalog_sync(
        self, principal_id: str, generation: str, attempt_id: str, timestamp: datetime
    ) -> GoogleDriveCatalogSync:
        for _ in range(2):
            try:
                connection = self._db.scalar(
                    select(GoogleDriveConnection)
                    .where(GoogleDriveConnection.principal_id == principal_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if connection is None or connection.catalog_generation != generation:
                    raise GoogleDriveError(
                        "The Google Drive connection changed before synchronization started."
                    )
                sync = self._db.get(GoogleDriveCatalogSync, principal_id)
                recovery = False
                if sync is not None and sync.status == "syncing" and sync.attempt_id is not None:
                    last_started = _as_utc(sync.last_started_at)
                    if last_started and last_started > timestamp - self._active_sync_timeout:
                        raise ActiveGoogleDriveSyncError(
                            "A Drive catalog synchronization is already in progress."
                        )
                    recovery = True
                    stale_attempt = self._db.get(GoogleDriveSyncAttempt, sync.attempt_id)
                    if stale_attempt is not None and stale_attempt.status == "running":
                        stale_attempt.status = "failed"
                        stale_attempt.phase = "failed"
                        stale_attempt.retryable = True
                        stale_attempt.error = "The synchronization became stale and was recovered."
                        stale_attempt.completed_at = timestamp
                mode = (
                    "recovery"
                    if recovery
                    else ("incremental" if sync and sync.change_page_token else "full")
                )
                if sync is None:
                    sync = GoogleDriveCatalogSync(
                        principal_id=principal_id,
                        attempt_id=attempt_id,
                        status="syncing",
                        mode=mode,
                        phase="fetching",
                        recovery=recovery,
                        last_started_at=timestamp,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                    self._db.add(sync)
                else:
                    sync.attempt_id = attempt_id
                    sync.status = "syncing"
                    sync.mode = mode
                    sync.phase = "fetching"
                    sync.processed_count = 0
                    sync.total_count = None
                    sync.retryable = False
                    sync.recovery = recovery
                    sync.last_started_at = timestamp
                    sync.last_error = None
                    sync.updated_at = timestamp
                self._db.add(
                    GoogleDriveSyncAttempt(
                        id=attempt_id,
                        principal_id=principal_id,
                        mode=mode,
                        status="running",
                        phase="fetching",
                        recovery=recovery,
                        started_at=timestamp,
                    )
                )
                self._db.commit()
                self._db.refresh(sync)
                return sync
            except GoogleDriveError:
                self._db.rollback()
                raise
            except SQLAlchemyError:
                self._db.rollback()
        raise GoogleDriveError("The Drive catalog synchronization could not start.")

    def _mark_recovery(self, principal_id: str, attempt_id: str) -> None:
        sync = self._lock_sync_attempt(principal_id, attempt_id)
        attempt = self._db.get(GoogleDriveSyncAttempt, attempt_id)
        if attempt is None:
            raise GoogleDriveError("The Drive synchronization history could not be updated.")
        sync.mode = "recovery"
        sync.phase = "fetching"
        sync.recovery = True
        sync.updated_at = datetime.now(UTC)
        attempt.mode = "recovery"
        attempt.phase = "fetching"
        attempt.recovery = True
        self._db.commit()

    def _mark_applying(self, principal_id: str, attempt_id: str, total: int) -> None:
        sync = self._lock_sync_attempt(principal_id, attempt_id)
        attempt = self._db.get(GoogleDriveSyncAttempt, attempt_id)
        if attempt is None:
            raise GoogleDriveError("The Drive synchronization history could not be updated.")
        sync.phase = "applying"
        sync.total_count = total
        sync.updated_at = datetime.now(UTC)
        attempt.phase = "applying"
        attempt.total_count = total
        self._db.commit()

    def exchange_code(self, principal_id: str, code: str) -> None:
        if not self._settings.google_is_configured:
            raise GoogleDriveError("Google Drive is not configured.")
        response = self._post_form(
            GOOGLE_TOKEN_URL,
            {
                "code": code,
                "client_id": self._settings.google_client_id or "",
                "client_secret": self._settings.google_client_secret.get_secret_value(),
                "redirect_uri": self._settings.google_redirect_uri or "",
                "grant_type": "authorization_code",
            },
        )
        refresh_token = response.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise GoogleDriveError(
                "Google did not return a refresh token. Reconnect and grant consent."
            )
        granted_scopes = str(response.get("scope") or GOOGLE_DRIVE_SCOPE)
        if GOOGLE_DRIVE_SCOPE not in granted_scopes.split():
            raise GoogleDriveError("Google Drive metadata access was not granted.")

        timestamp = datetime.now(UTC)
        connection = GoogleDriveConnection(
            principal_id=principal_id,
            refresh_token_encrypted=self._encrypt(refresh_token),
            granted_scopes=granted_scopes,
            catalog_generation=str(uuid.uuid4()),
            created_at=timestamp,
            updated_at=timestamp,
        )
        existing = self._db.get(GoogleDriveConnection, principal_id)
        if existing is not None:
            self._delete_catalog(principal_id)
            self._db.delete(existing)
            self._db.flush()
        self._db.add(connection)
        try:
            self._refresh(connection, commit=False)
            self._db.commit()
        except GoogleDriveError:
            self._db.rollback()
            raise

    def disconnect(self, principal_id: str) -> None:
        connection = self._db.get(GoogleDriveConnection, principal_id)
        if connection is None:
            return
        # Local deletion prevents future API access even if Google is unreachable.
        with suppress(GoogleDriveError):
            self._post_form(
                "https://oauth2.googleapis.com/revoke",
                {"token": self._decrypt(connection.refresh_token_encrypted)},
            )
        self._delete_catalog(principal_id)
        self._db.delete(connection)
        self._db.commit()

    def _fetch_full_catalog(
        self, access_token: str, deadline: float, root_folder_id: str
    ) -> tuple[dict[str, _CatalogRecord], str]:
        start_payload = self._get_json(
            GOOGLE_START_PAGE_TOKEN_URL,
            access_token,
            {"supportsAllDrives": "false"},
        )
        start_token = _required_str(start_payload.get("startPageToken"))
        records: dict[str, _CatalogRecord] = {}
        page_token: str | None = None
        for _ in range(self._catalog_page_limit):
            self._check_sync_deadline(deadline)
            parameters = {
                "corpora": "user",
                "spaces": "drive",
                "q": "'me' in owners and trashed = false",
                "pageSize": "500",
                "fields": f"nextPageToken,files({GOOGLE_FILE_FIELDS})",
            }
            if page_token:
                parameters["pageToken"] = page_token
            payload = self._get_json(GOOGLE_FILES_URL, access_token, parameters)
            files = payload.get("files")
            if not isinstance(files, list):
                raise GoogleDriveError("Google Drive returned an unexpected catalog response.")
            for value in files:
                record = _catalog_record(value, root_folder_id)
                if record is not None:
                    records[record.file_id] = record
            page_token = _optional_str(payload.get("nextPageToken"))
            if page_token is None:
                break
        else:
            raise GoogleDriveError("The Drive catalog exceeds the synchronization page limit.")

        changes, next_token = self._fetch_changes(
            access_token, start_token, deadline, root_folder_id
        )
        for removed, file_id, record in changes:
            if removed:
                records.pop(file_id, None)
            elif record is not None:
                records[file_id] = record
        return records, next_token

    def _fetch_changes(
        self, access_token: str, page_token: str, deadline: float, root_folder_id: str
    ) -> tuple[list[tuple[bool, str, _CatalogRecord | None]], str]:
        changes: list[tuple[bool, str, _CatalogRecord | None]] = []
        current_token = page_token
        for _ in range(self._catalog_page_limit):
            self._check_sync_deadline(deadline)
            payload = self._get_json(
                GOOGLE_CHANGES_URL,
                access_token,
                {
                    "pageToken": current_token,
                    "spaces": "drive",
                    "includeRemoved": "true",
                    "includeItemsFromAllDrives": "false",
                    "restrictToMyDrive": "true",
                    "pageSize": "500",
                    "fields": (
                        "nextPageToken,newStartPageToken,"
                        f"changes(fileId,removed,file({GOOGLE_FILE_FIELDS}))"
                    ),
                },
            )
            values = payload.get("changes")
            if not isinstance(values, list):
                raise GoogleDriveError("Google Drive returned an unexpected changes response.")
            for value in values:
                if not isinstance(value, dict):
                    raise GoogleDriveError("Google Drive returned invalid change metadata.")
                file_id = _required_str(value.get("fileId"))
                removed = value.get("removed") is True
                record = None if removed else _catalog_record(value.get("file"), root_folder_id)
                changes.append((removed or record is None, file_id, record))

            next_page_token = _optional_str(payload.get("nextPageToken"))
            if next_page_token:
                current_token = next_page_token
                continue
            return changes, _required_str(payload.get("newStartPageToken"))
        raise GoogleDriveError("The Drive changes feed exceeds the synchronization page limit.")

    def _check_sync_deadline(self, deadline: float) -> None:
        if time.monotonic() >= deadline:
            raise GoogleDriveError("The Drive catalog synchronization timed out.")

    def _fetch_root_folder_id(self, access_token: str) -> str:
        payload = self._get_json(
            f"{GOOGLE_FILES_URL}/root",
            access_token,
            {"fields": "id", "supportsAllDrives": "false"},
        )
        return _required_str(payload.get("id"))

    def _lock_connection(self, principal_id: str, generation: str) -> GoogleDriveConnection:
        current = self._db.scalar(
            select(GoogleDriveConnection)
            .where(GoogleDriveConnection.principal_id == principal_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current is None or current.catalog_generation != generation:
            raise GoogleDriveError("The Google Drive connection changed during synchronization.")
        return current

    def _lock_sync_attempt(self, principal_id: str, attempt_id: str) -> GoogleDriveCatalogSync:
        sync = self._db.scalar(
            select(GoogleDriveCatalogSync)
            .where(GoogleDriveCatalogSync.principal_id == principal_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if sync is None or sync.attempt_id != attempt_id:
            raise GoogleDriveError("A newer Drive catalog synchronization has started.")
        return sync

    def _replace_catalog(
        self, principal_id: str, records: dict[str, _CatalogRecord], indexed_at: datetime
    ) -> None:
        self._db.execute(
            delete(GoogleDriveParentEdge).where(GoogleDriveParentEdge.principal_id == principal_id)
        )
        self._db.execute(
            delete(GoogleDriveCatalogItem).where(
                GoogleDriveCatalogItem.principal_id == principal_id
            )
        )
        self._db.add_all(
            [_catalog_model(principal_id, record, indexed_at) for record in records.values()]
        )
        self._db.add_all(
            [
                GoogleDriveParentEdge(
                    principal_id=principal_id,
                    child_file_id=record.file_id,
                    parent_file_id=parent_id,
                )
                for record in records.values()
                for parent_id in record.parent_ids
            ]
        )
        self._db.flush()

    def _apply_changes(
        self,
        principal_id: str,
        changes: list[tuple[bool, str, _CatalogRecord | None]],
        indexed_at: datetime,
    ) -> None:
        for removed, file_id, record in changes:
            key = (principal_id, file_id)
            existing = self._db.get(GoogleDriveCatalogItem, key)
            if removed:
                self._db.execute(
                    delete(GoogleDriveParentEdge).where(
                        GoogleDriveParentEdge.principal_id == principal_id,
                        GoogleDriveParentEdge.child_file_id == file_id,
                    )
                )
                if existing is not None:
                    self._add_activity(
                        principal_id,
                        "removed",
                        f"Removed metadata observed for {existing.name}.",
                        indexed_at,
                        file_id=file_id,
                        name=existing.name,
                        kind=drive_kind(existing.mime_type),
                    )
                    self._db.delete(existing)
                continue
            if record is None:
                continue
            event_type = "created" if existing is None else "modified"
            if existing is None:
                self._db.add(_catalog_model(principal_id, record, indexed_at))
            else:
                _update_catalog_model(existing, record, indexed_at)
            self._db.execute(
                delete(GoogleDriveParentEdge).where(
                    GoogleDriveParentEdge.principal_id == principal_id,
                    GoogleDriveParentEdge.child_file_id == file_id,
                )
            )
            self._db.add_all(
                [
                    GoogleDriveParentEdge(
                        principal_id=principal_id,
                        child_file_id=file_id,
                        parent_file_id=parent_id,
                    )
                    for parent_id in record.parent_ids
                ]
            )
            self._add_activity(
                principal_id,
                event_type,
                f"{event_type.capitalize()} metadata observed for {record.name}.",
                indexed_at,
                file_id=file_id,
                name=record.name,
                kind=drive_kind(record.mime_type),
            )
        self._db.flush()

    def _delete_catalog(self, principal_id: str) -> None:
        for model in (
            GoogleDriveParentEdge,
            GoogleDriveCatalogItem,
            GoogleDriveActivity,
            GoogleDriveSyncAttempt,
            GoogleDrivePinnedLocation,
            GoogleDriveSavedSearch,
            GoogleDriveCatalogSync,
        ):
            self._db.execute(delete(model).where(model.principal_id == principal_id))

    def _add_activity(
        self,
        principal_id: str,
        event_type: str,
        summary: str,
        observed_at: datetime,
        *,
        file_id: str | None = None,
        name: str | None = None,
        kind: str | None = None,
    ) -> None:
        self._db.add(
            GoogleDriveActivity(
                id=str(uuid.uuid4()),
                principal_id=principal_id,
                event_type=event_type,
                drive_file_id=file_id,
                name=name,
                kind=kind,
                summary=summary[:500],
                observed_at=observed_at,
            )
        )

    def _prune_history(self, principal_id: str) -> None:
        self._db.flush()
        old_activity_ids = list(
            self._db.scalars(
                select(GoogleDriveActivity.id)
                .where(GoogleDriveActivity.principal_id == principal_id)
                .order_by(GoogleDriveActivity.observed_at.desc(), GoogleDriveActivity.id.desc())
                .offset(self._activity_retention)
            )
        )
        if old_activity_ids:
            self._db.execute(
                delete(GoogleDriveActivity).where(GoogleDriveActivity.id.in_(old_activity_ids))
            )
        old_attempt_ids = list(
            self._db.scalars(
                select(GoogleDriveSyncAttempt.id)
                .where(GoogleDriveSyncAttempt.principal_id == principal_id)
                .order_by(
                    GoogleDriveSyncAttempt.started_at.desc(), GoogleDriveSyncAttempt.id.desc()
                )
                .offset(self._attempt_retention)
            )
        )
        if old_attempt_ids:
            self._db.execute(
                delete(GoogleDriveSyncAttempt).where(GoogleDriveSyncAttempt.id.in_(old_attempt_ids))
            )

    def _refresh(self, connection: GoogleDriveConnection, commit: bool = True) -> None:
        access_token = self._access_token(connection)
        request = Request(
            f"{GOOGLE_ABOUT_URL}?fields=user(displayName,emailAddress),storageQuota(limit,usage)",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        payload = self._request_json(request)
        user = payload.get("user")
        quota = payload.get("storageQuota")
        if not isinstance(user, dict) or not isinstance(quota, dict):
            raise GoogleDriveError("Google Drive returned an unexpected status response.")
        used = _optional_int(quota.get("usage"))
        total = _optional_int(quota.get("limit"))
        timestamp = datetime.now(UTC)
        connection.account_email = _optional_str(user.get("emailAddress"))
        connection.account_name = _optional_str(user.get("displayName"))
        connection.used_bytes = used
        connection.total_bytes = total
        connection.last_checked_at = timestamp
        connection.last_error = None
        connection.updated_at = timestamp
        if commit:
            self._db.commit()

    def _access_token(self, connection: GoogleDriveConnection) -> str:
        response = self._post_form(
            GOOGLE_TOKEN_URL,
            {
                "client_id": self._settings.google_client_id or "",
                "client_secret": self._settings.google_client_secret.get_secret_value(),
                "refresh_token": self._decrypt(connection.refresh_token_encrypted),
                "grant_type": "refresh_token",
            },
        )
        access_token = response.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise GoogleDriveError("Google Drive authorization needs to be reconnected.")
        return access_token

    def _summary_from_connection(
        self, connection: GoogleDriveConnection, fallback_checked_at: datetime
    ) -> GoogleDriveSummary:
        checked_at = _as_utc(connection.last_checked_at) or fallback_checked_at
        if connection.last_error:
            return GoogleDriveSummary(
                state="unavailable",
                account_email=connection.account_email,
                account_name=connection.account_name,
                message=connection.last_error,
                checked_at=checked_at,
            )
        available = None
        percent = None
        if connection.total_bytes is not None and connection.used_bytes is not None:
            available = max(0, connection.total_bytes - connection.used_bytes)
            if connection.total_bytes > 0:
                percent = connection.used_bytes / connection.total_bytes * 100
        return GoogleDriveSummary(
            state="healthy",
            account_email=connection.account_email,
            account_name=connection.account_name,
            used_bytes=connection.used_bytes,
            total_bytes=connection.total_bytes,
            available_bytes=available,
            percent=percent,
            message="Google Drive status is current.",
            checked_at=checked_at,
        )

    def _encrypt(self, value: str) -> str:
        try:
            return (
                Fernet(self._settings.google_token_encryption_key.get_secret_value().encode())
                .encrypt(value.encode())
                .decode()
            )
        except (ValueError, TypeError) as error:
            raise GoogleDriveError(
                "Google token encryption is not configured correctly."
            ) from error

    def _decrypt(self, value: str) -> str:
        try:
            return (
                Fernet(self._settings.google_token_encryption_key.get_secret_value().encode())
                .decrypt(value.encode())
                .decode()
            )
        except (InvalidToken, ValueError, TypeError) as error:
            raise GoogleDriveError("Google Drive authorization needs to be reconnected.") from error

    def _post_form(self, url: str, values: dict[str, str]) -> dict[str, Any]:
        request = Request(
            url,
            data=urlencode(values).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        return self._request_json(request)

    def _get_json(self, url: str, access_token: str, parameters: dict[str, str]) -> dict[str, Any]:
        request = Request(
            f"{url}?{urlencode(parameters)}",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        return self._request_json(request)

    def _request_json(self, request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=5) as response:  # noqa: S310 - fixed Google origins only
                payload = json.loads(response.read(1_000_000))
        except HTTPError as error:
            if error.code == 410:
                raise _ExpiredChangeTokenError(
                    "The Drive changes cursor expired. Rebuilding the metadata catalog."
                ) from error
            if error.code in {400, 401}:
                raise GoogleDriveError(
                    "Google Drive authorization needs to be reconnected."
                ) from error
            if error.code == 429:
                raise GoogleDriveError(
                    "Google Drive is rate limiting requests. Try again later."
                ) from error
            raise GoogleDriveError("Google Drive is unavailable.") from error
        except (HTTPClientError, OSError, TimeoutError, URLError, json.JSONDecodeError) as error:
            raise GoogleDriveError("Google Drive is unavailable.") from error
        if not isinstance(payload, dict):
            raise GoogleDriveError("Google Drive returned an unexpected response.")
        return payload


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        number = int(str(value))
    except TypeError, ValueError:
        return None
    return number if number >= 0 else None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _required_str(value: object) -> str:
    result = _optional_str(value)
    if result is None:
        raise GoogleDriveError("Google Drive returned incomplete catalog metadata.")
    return result


def _optional_datetime(value: object) -> datetime | None:
    text = _optional_str(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise GoogleDriveError("Google Drive returned an invalid catalog timestamp.") from error
    return _as_utc(parsed)


def _catalog_record(value: object, root_folder_id: str) -> _CatalogRecord | None:
    if not isinstance(value, dict):
        raise GoogleDriveError("Google Drive returned invalid file metadata.")
    if value.get("trashed") is True or value.get("ownedByMe") is not True:
        return None
    modified_at = _optional_datetime(value.get("modifiedTime"))
    if modified_at is None:
        raise GoogleDriveError("Google Drive returned incomplete file metadata.")
    parent_values = value.get("parents", [])
    if not isinstance(parent_values, list) or not all(
        isinstance(parent, str) for parent in parent_values
    ):
        raise GoogleDriveError("Google Drive returned invalid parent metadata.")
    return _CatalogRecord(
        file_id=_required_str(value.get("id")),
        name=_required_str(value.get("name")),
        mime_type=_required_str(value.get("mimeType")),
        size_bytes=_optional_int(value.get("size")),
        created_at=_optional_datetime(value.get("createdTime")),
        modified_at=modified_at,
        parent_ids=list(
            dict.fromkeys(
                "root" if parent == root_folder_id else parent for parent in parent_values
            )
        ),
        starred=value.get("starred") is True,
        owned_by_me=True,
    )


def _catalog_model(
    principal_id: str, record: _CatalogRecord, indexed_at: datetime
) -> GoogleDriveCatalogItem:
    return GoogleDriveCatalogItem(
        principal_id=principal_id,
        drive_file_id=record.file_id,
        name=record.name,
        name_search=record.name.casefold(),
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        drive_created_at=record.created_at,
        drive_modified_at=record.modified_at,
        web_url=f"https://drive.google.com/open?id={quote(record.file_id, safe='')}",
        parent_ids=record.parent_ids,
        starred=record.starred,
        owned_by_me=record.owned_by_me,
        indexed_at=indexed_at,
    )


def _update_catalog_model(
    item: GoogleDriveCatalogItem, record: _CatalogRecord, indexed_at: datetime
) -> None:
    item.name = record.name
    item.name_search = record.name.casefold()
    item.mime_type = record.mime_type
    item.size_bytes = record.size_bytes
    item.drive_created_at = record.created_at
    item.drive_modified_at = record.modified_at
    item.web_url = f"https://drive.google.com/open?id={quote(record.file_id, safe='')}"
    item.parent_ids = record.parent_ids
    item.starred = record.starred
    item.owned_by_me = record.owned_by_me
    item.indexed_at = indexed_at


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _is_retryable_error(error: Exception) -> bool:
    if isinstance(error, SQLAlchemyError):
        return True
    message = str(error).casefold()
    return not any(value in message for value in ("authorization", "reconnect", "not configured"))
