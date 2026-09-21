import base64
import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.auth.service import Principal
from app.core.database import get_db_session
from app.dependencies import get_google_drive_integration, require_principal
from app.integrations.google_drive import GoogleDriveIntegration
from app.models import GoogleDriveCatalogItem
from app.schemas.search import SearchResponse, SearchResult

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
def search(
    principal: Annotated[Principal, Depends(require_principal)],
    db: Annotated[Session, Depends(get_db_session)],
    drive: Annotated[GoogleDriveIntegration, Depends(get_google_drive_integration)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResponse:
    query_text = q.strip()
    if not query_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Search query must not be blank.",
        )

    escaped = query_text.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    statement = (
        select(GoogleDriveCatalogItem)
        .where(
            GoogleDriveCatalogItem.principal_id == principal.id,
            GoogleDriveCatalogItem.name_search.ilike(f"%{escaped}%", escape="\\"),
        )
        .order_by(
            GoogleDriveCatalogItem.drive_modified_at.desc(),
            GoogleDriveCatalogItem.drive_file_id.asc(),
        )
    )
    if cursor:
        cursor_time, cursor_file_id = _decode_cursor(cursor)
        statement = statement.where(
            or_(
                GoogleDriveCatalogItem.drive_modified_at < cursor_time,
                and_(
                    GoogleDriveCatalogItem.drive_modified_at == cursor_time,
                    GoogleDriveCatalogItem.drive_file_id > cursor_file_id,
                ),
            )
        )

    values = list(db.scalars(statement.limit(limit + 1)))
    has_more = len(values) > limit
    values = values[:limit]
    next_cursor = None
    if has_more and values:
        last = values[-1]
        next_cursor = _encode_cursor(last.drive_modified_at, last.drive_file_id)

    return SearchResponse(
        items=[
            SearchResult(
                id=item.drive_file_id,
                name=item.name,
                mime_type=item.mime_type,
                size_bytes=item.size_bytes,
                modified_at=item.drive_modified_at,
                web_url=item.web_url,
            )
            for item in values
        ],
        next_cursor=next_cursor,
        catalog=drive.catalog_status(principal.id),
    )


def _encode_cursor(modified_at: datetime, file_id: str) -> str:
    if modified_at.tzinfo is None:
        modified_at = modified_at.replace(tzinfo=UTC)
    payload = json.dumps([modified_at.isoformat(), file_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, str]:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
        payload = json.loads(decoded)
        if (
            not isinstance(payload, list)
            or len(payload) != 2
            or not isinstance(payload[0], str)
            or not isinstance(payload[1], str)
            or not payload[1]
        ):
            raise ValueError
        modified_at = datetime.fromisoformat(payload[0])
        if modified_at.tzinfo is None:
            raise ValueError
        return modified_at.astimezone(UTC), payload[1]
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search cursor is invalid.",
        ) from error
