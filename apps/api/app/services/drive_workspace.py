import base64
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, case, exists, not_, or_, select
from sqlalchemy.orm import Session

from app.models import (
    GoogleDriveActivity,
    GoogleDriveCatalogItem,
    GoogleDriveCatalogSync,
    GoogleDriveConnection,
    GoogleDriveParentEdge,
    GoogleDrivePinnedLocation,
    GoogleDriveSyncAttempt,
)
from app.schemas.drive_workspace import (
    DriveActivityEvent,
    DriveActivityResponse,
    DriveFolder,
    DriveInsights,
    DriveItemsResponse,
    InsightFile,
    KindInsight,
    PinnedLocation,
    SyncAttempt,
    SyncAttemptList,
)
from app.schemas.search import DriveCatalogStatus, DriveParentSummary, SearchResult

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
_DOCUMENT_MIME_TYPES = {
    "application/pdf",
    "application/rtf",
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.presentation",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/csv",
    "text/plain",
}
_ARCHIVE_MIME_TYPES = {
    "application/gzip",
    "application/vnd.rar",
    "application/x-7z-compressed",
    "application/x-tar",
    "application/zip",
}


@dataclass(frozen=True)
class DriveListFilters:
    q: str | None = None
    view: str = "all"
    kind: str = "all"
    parent_id: str | None = None
    modified_after: datetime | None = None
    modified_before: datetime | None = None
    min_size: int | None = None
    max_size: int | None = None
    starred: bool | None = None
    ownership: str = "owned_by_me"
    sort: str = "modified"
    direction: str = "desc"

    def signature(self) -> str:
        values = asdict(self)
        for key in ("modified_after", "modified_before"):
            value = values[key]
            if value is not None:
                values[key] = _as_utc(value).isoformat()
        encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class DriveWorkspace:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_items(
        self,
        principal_id: str,
        filters: DriveListFilters,
        cursor: str | None,
        limit: int,
        catalog: DriveCatalogStatus,
    ) -> DriveItemsResponse:
        revision = self._revision(principal_id)
        offset = self._cursor_offset(principal_id, cursor, filters, revision)
        item = GoogleDriveCatalogItem
        statement = select(item).where(
            item.principal_id == principal_id, item.owned_by_me.is_(True)
        )
        if filters.q:
            escaped = _escape_like(filters.q.casefold())
            statement = statement.where(item.name_search.ilike(f"%{escaped}%", escape="\\"))
        if filters.view == "recent":
            statement = statement.where(
                item.drive_modified_at >= datetime.now(UTC) - timedelta(days=30)
            )
        elif filters.view == "starred":
            statement = statement.where(item.starred.is_(True))
        if filters.starred is not None:
            statement = statement.where(item.starred.is_(filters.starred))
        if filters.kind != "all":
            statement = statement.where(_kind_predicate(filters.kind))
        if filters.parent_id:
            statement = statement.where(
                exists(
                    select(GoogleDriveParentEdge.child_file_id).where(
                        GoogleDriveParentEdge.principal_id == principal_id,
                        GoogleDriveParentEdge.child_file_id == item.drive_file_id,
                        GoogleDriveParentEdge.parent_file_id == filters.parent_id,
                    )
                )
            )
        if filters.modified_after:
            statement = statement.where(item.drive_modified_at >= filters.modified_after)
        if filters.modified_before:
            statement = statement.where(item.drive_modified_at < filters.modified_before)
        if filters.min_size is not None:
            statement = statement.where(item.size_bytes >= filters.min_size)
        if filters.max_size is not None:
            statement = statement.where(item.size_bytes <= filters.max_size)

        sort_column = {
            "modified": item.drive_modified_at,
            "created": item.drive_created_at,
            "name": item.name_search,
            "size": item.size_bytes,
        }[filters.sort]
        null_rank = case((sort_column.is_(None), 1), else_=0)
        ordered = sort_column.asc() if filters.direction == "asc" else sort_column.desc()
        id_order = (
            item.drive_file_id.asc() if filters.direction == "asc" else item.drive_file_id.desc()
        )
        statement = (
            statement.order_by(null_rank.asc(), ordered, id_order).offset(offset).limit(limit + 1)
        )
        values = list(self._db.scalars(statement))
        has_more = len(values) > limit
        values = values[:limit]
        parents = self._parent_summaries(principal_id, values)
        if self._revision(principal_id) != revision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The Drive catalog changed; retry the request.",
            )
        catalog.revision = revision
        next_cursor = None
        if has_more:
            next_cursor = _encode_cursor(
                principal_id, revision, filters.signature(), offset + limit
            )
        return DriveItemsResponse(
            items=[_item_schema(value, parents.get(value.drive_file_id)) for value in values],
            next_cursor=next_cursor,
            catalog=catalog,
        )

    def folder(self, principal_id: str, folder_id: str) -> DriveFolder:
        if folder_id == "root":
            return DriveFolder(
                id="root",
                name="My Drive",
                web_url="https://drive.google.com/drive/my-drive",
                breadcrumbs=[DriveParentSummary(id="root", name="My Drive")],
            )
        item = self._db.get(GoogleDriveCatalogItem, (principal_id, folder_id))
        if item is None or item.mime_type != FOLDER_MIME_TYPE:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found.")

        complete = True
        seen = {folder_id}
        chain = [DriveParentSummary(id=item.drive_file_id, name=item.name)]
        current_id = folder_id
        for _ in range(50):
            parent_id = self._db.scalar(
                select(GoogleDriveParentEdge.parent_file_id)
                .where(
                    GoogleDriveParentEdge.principal_id == principal_id,
                    GoogleDriveParentEdge.child_file_id == current_id,
                )
                .order_by(GoogleDriveParentEdge.parent_file_id.asc())
                .limit(1)
            )
            if parent_id is None:
                complete = False
                break
            if parent_id == "root":
                chain.append(DriveParentSummary(id="root", name="My Drive"))
                break
            if parent_id in seen:
                complete = False
                break
            seen.add(parent_id)
            parent = self._db.get(GoogleDriveCatalogItem, (principal_id, parent_id))
            if parent is None or parent.mime_type != FOLDER_MIME_TYPE:
                chain.append(
                    DriveParentSummary(id=parent_id, name="Unavailable folder", available=False)
                )
                complete = False
                break
            chain.append(DriveParentSummary(id=parent.drive_file_id, name=parent.name))
            current_id = parent_id
        else:
            complete = False
        return DriveFolder(
            id=item.drive_file_id,
            name=item.name,
            web_url=item.web_url,
            modified_at=item.drive_modified_at,
            starred=item.starred,
            breadcrumbs=list(reversed(chain)),
            breadcrumbs_complete=complete,
        )

    def pins(self, principal_id: str) -> list[PinnedLocation]:
        pins = list(
            self._db.scalars(
                select(GoogleDrivePinnedLocation)
                .where(GoogleDrivePinnedLocation.principal_id == principal_id)
                .order_by(
                    GoogleDrivePinnedLocation.created_at.asc(),
                    GoogleDrivePinnedLocation.id.asc(),
                )
            )
        )
        folder_ids = [pin.drive_folder_id for pin in pins]
        folders = {}
        if folder_ids:
            folders = {
                item.drive_file_id: item
                for item in self._db.scalars(
                    select(GoogleDriveCatalogItem).where(
                        GoogleDriveCatalogItem.principal_id == principal_id,
                        GoogleDriveCatalogItem.drive_file_id.in_(folder_ids),
                        GoogleDriveCatalogItem.mime_type == FOLDER_MIME_TYPE,
                    )
                )
            }
        return [
            PinnedLocation(
                id=pin.id,
                drive_folder_id=pin.drive_folder_id,
                label=pin.label,
                folder_name=folders[pin.drive_folder_id].name
                if pin.drive_folder_id in folders
                else None,
                available=pin.drive_folder_id in folders,
                web_url=folders[pin.drive_folder_id].web_url
                if pin.drive_folder_id in folders
                else None,
                created_at=pin.created_at,
            )
            for pin in pins
        ]

    def insights(self, principal_id: str) -> DriveInsights:
        connection = self._db.get(GoogleDriveConnection, principal_id)
        if connection is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Drive not connected."
            )
        items = list(
            self._db.scalars(
                select(GoogleDriveCatalogItem).where(
                    GoogleDriveCatalogItem.principal_id == principal_id
                )
            )
        )
        groups: dict[str, list[GoogleDriveCatalogItem]] = {}
        for item in items:
            groups.setdefault(drive_kind(item.mime_type), []).append(item)
        by_kind = [
            KindInsight(
                kind=kind,  # type: ignore[arg-type]
                item_count=len(values),
                known_size_bytes=sum(value.size_bytes or 0 for value in values),
                unknown_size_count=sum(value.size_bytes is None for value in values),
            )
            for kind, values in sorted(groups.items())
        ]
        files = [item for item in items if drive_kind(item.mime_type) != "folder"]
        largest = sorted(
            (item for item in files if item.size_bytes is not None),
            key=lambda value: (-(value.size_bytes or 0), value.drive_file_id),
        )[:10]
        stale_before = datetime.now(UTC) - timedelta(days=365)
        stale = sorted(
            (item for item in files if _as_utc(item.drive_modified_at) < stale_before),
            key=lambda value: (value.drive_modified_at, value.drive_file_id),
        )[:10]
        sync = self._db.get(GoogleDriveCatalogSync, principal_id)
        return DriveInsights(
            account_used_bytes=connection.used_bytes,
            account_total_bytes=connection.total_bytes,
            catalog_known_size_bytes=sum(item.size_bytes or 0 for item in items),
            catalog_unknown_size_count=sum(item.size_bytes is None for item in items),
            by_kind=by_kind,
            largest_files=[_insight_file(item) for item in largest],
            stale_files=[_insight_file(item) for item in stale],
            freshness_at=sync.last_completed_at if sync else None,
        )

    def sync_history(self, principal_id: str, limit: int) -> SyncAttemptList:
        attempts = self._db.scalars(
            select(GoogleDriveSyncAttempt)
            .where(GoogleDriveSyncAttempt.principal_id == principal_id)
            .order_by(GoogleDriveSyncAttempt.started_at.desc(), GoogleDriveSyncAttempt.id.desc())
            .limit(limit)
        )
        return SyncAttemptList(
            items=[
                SyncAttempt(
                    id=value.id,
                    mode=value.mode,  # type: ignore[arg-type]
                    status=value.status,  # type: ignore[arg-type]
                    phase=value.phase,  # type: ignore[arg-type]
                    processed_count=value.processed_count,
                    total_count=value.total_count,
                    retryable=value.retryable,
                    recovery=value.recovery,
                    error=value.error,
                    started_at=value.started_at,
                    completed_at=value.completed_at,
                )
                for value in attempts
            ]
        )

    def activity(self, principal_id: str, cursor: str | None, limit: int) -> DriveActivityResponse:
        statement = select(GoogleDriveActivity).where(
            GoogleDriveActivity.principal_id == principal_id
        )
        if cursor:
            observed_at, activity_id = _decode_activity_cursor(cursor, principal_id)
            statement = statement.where(
                or_(
                    GoogleDriveActivity.observed_at < observed_at,
                    and_(
                        GoogleDriveActivity.observed_at == observed_at,
                        GoogleDriveActivity.id < activity_id,
                    ),
                )
            )
        values = list(
            self._db.scalars(
                statement.order_by(
                    GoogleDriveActivity.observed_at.desc(), GoogleDriveActivity.id.desc()
                ).limit(limit + 1)
            )
        )
        has_more = len(values) > limit
        values = values[:limit]
        return DriveActivityResponse(
            items=[
                DriveActivityEvent(
                    id=value.id,
                    event_type=value.event_type,  # type: ignore[arg-type]
                    file_id=value.drive_file_id,
                    name=value.name,
                    kind=value.kind,  # type: ignore[arg-type]
                    summary=value.summary,
                    observed_at=value.observed_at,
                )
                for value in values
            ],
            next_cursor=(
                _encode_activity_cursor(principal_id, values[-1]) if has_more and values else None
            ),
        )

    def _revision(self, principal_id: str) -> int:
        return (
            self._db.scalar(
                select(GoogleDriveCatalogSync.catalog_revision).where(
                    GoogleDriveCatalogSync.principal_id == principal_id
                )
            )
            or 0
        )

    def _cursor_offset(
        self,
        principal_id: str,
        cursor: str | None,
        filters: DriveListFilters,
        revision: int,
    ) -> int:
        if cursor is None:
            return 0
        payload = _decode_cursor(cursor)
        if payload.get("p") != principal_id or payload.get("f") != filters.signature():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cursor does not match the requested filters.",
            )
        if payload.get("r") != revision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The Drive catalog changed; restart pagination.",
            )
        offset = payload.get("o")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Cursor is invalid."
            )
        return offset

    def _parent_summaries(
        self, principal_id: str, items: list[GoogleDriveCatalogItem]
    ) -> dict[str, DriveParentSummary]:
        if not items:
            return {}
        child_ids = [item.drive_file_id for item in items]
        edges = list(
            self._db.execute(
                select(GoogleDriveParentEdge.child_file_id, GoogleDriveParentEdge.parent_file_id)
                .where(
                    GoogleDriveParentEdge.principal_id == principal_id,
                    GoogleDriveParentEdge.child_file_id.in_(child_ids),
                )
                .order_by(
                    GoogleDriveParentEdge.child_file_id.asc(),
                    GoogleDriveParentEdge.parent_file_id.asc(),
                )
            )
        )
        first_parent: dict[str, str] = {}
        for child_id, parent_id in edges:
            first_parent.setdefault(child_id, parent_id)
        catalog_parent_ids = {value for value in first_parent.values() if value != "root"}
        parent_names = {}
        if catalog_parent_ids:
            parent_names = {
                file_id: name
                for file_id, name in self._db.execute(
                    select(GoogleDriveCatalogItem.drive_file_id, GoogleDriveCatalogItem.name).where(
                        GoogleDriveCatalogItem.principal_id == principal_id,
                        GoogleDriveCatalogItem.drive_file_id.in_(catalog_parent_ids),
                    )
                )
            }
        result = {}
        for child_id, parent_id in first_parent.items():
            if parent_id == "root":
                result[child_id] = DriveParentSummary(id="root", name="My Drive")
            elif parent_id in parent_names:
                result[child_id] = DriveParentSummary(id=parent_id, name=parent_names[parent_id])
            else:
                result[child_id] = DriveParentSummary(
                    id=parent_id, name="Unavailable folder", available=False
                )
        return result


def drive_kind(mime_type: str) -> str:
    if mime_type == FOLDER_MIME_TYPE:
        return "folder"
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type in _ARCHIVE_MIME_TYPES:
        return "archive"
    if mime_type in _DOCUMENT_MIME_TYPES or mime_type.startswith("text/"):
        return "document"
    return "other"


def _kind_predicate(kind: str):
    mime = GoogleDriveCatalogItem.mime_type
    predicates = {
        "folder": mime == FOLDER_MIME_TYPE,
        "image": mime.like("image/%"),
        "video": mime.like("video/%"),
        "audio": mime.like("audio/%"),
        "archive": mime.in_(_ARCHIVE_MIME_TYPES),
        "document": or_(mime.in_(_DOCUMENT_MIME_TYPES), mime.like("text/%")),
    }
    if kind in predicates:
        return predicates[kind]
    return not_(
        or_(
            mime == FOLDER_MIME_TYPE,
            mime.like("image/%"),
            mime.like("video/%"),
            mime.like("audio/%"),
            mime.in_(_ARCHIVE_MIME_TYPES),
            mime.in_(_DOCUMENT_MIME_TYPES),
            mime.like("text/%"),
        )
    )


def _item_schema(item: GoogleDriveCatalogItem, parent: DriveParentSummary | None) -> SearchResult:
    labels = []
    if item.starred:
        labels.append("starred")
    if _as_utc(item.drive_modified_at) >= datetime.now(UTC) - timedelta(days=30):
        labels.append("recent")
    return SearchResult(
        id=item.drive_file_id,
        name=item.name,
        mime_type=item.mime_type,
        kind=drive_kind(item.mime_type),  # type: ignore[arg-type]
        size_bytes=item.size_bytes,
        created_at=item.drive_created_at,
        modified_at=item.drive_modified_at,
        starred=item.starred,
        parent=parent,
        status_labels=labels,
        web_url=item.web_url,
    )


def _insight_file(item: GoogleDriveCatalogItem) -> InsightFile:
    return InsightFile(
        id=item.drive_file_id,
        name=item.name,
        kind=drive_kind(item.mime_type),  # type: ignore[arg-type]
        size_bytes=item.size_bytes,
        modified_at=item.drive_modified_at,
        web_url=item.web_url,
    )


def _encode_cursor(principal_id: str, revision: int, signature: str, offset: int) -> str:
    return _encode({"v": 1, "p": principal_id, "r": revision, "f": signature, "o": offset})


def _decode_cursor(value: str) -> dict[str, object]:
    payload = _decode(value)
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cursor is invalid.")
    return payload


def _encode_activity_cursor(principal_id: str, activity: GoogleDriveActivity) -> str:
    return _encode(
        {
            "v": 1,
            "p": principal_id,
            "t": _as_utc(activity.observed_at).isoformat(),
            "i": activity.id,
        }
    )


def _decode_activity_cursor(value: str, principal_id: str) -> tuple[datetime, str]:
    payload = _decode(value)
    try:
        if (
            not isinstance(payload, dict)
            or set(payload) != {"v", "p", "t", "i"}
            or payload.get("v") != 1
            or payload.get("p") != principal_id
            or not isinstance(payload.get("t"), str)
            or not isinstance(payload.get("i"), str)
            or not payload["i"]
        ):
            raise ValueError
        observed_at = datetime.fromisoformat(payload["t"])
        if observed_at.tzinfo is None:
            raise ValueError
        return observed_at.astimezone(UTC), payload["i"]
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cursor is invalid."
        ) from error


def _encode(payload: object) -> str:
    value = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> object:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
        return json.loads(decoded)
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cursor is invalid."
        ) from error


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
