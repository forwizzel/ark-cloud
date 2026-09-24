import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import AwareDatetime
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.service import SESSION_COOKIE, Principal, digest, get_session
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.dependencies import get_google_drive_integration, require_csrf, require_principal
from app.integrations.google_drive import (
    GOOGLE_DRIVE_SCOPE,
    ActiveGoogleDriveSyncError,
    GoogleDriveError,
    GoogleDriveIntegration,
)
from app.models import (
    AuthSession,
    GoogleDriveCatalogItem,
    GoogleDriveConnection,
    GoogleDrivePinnedLocation,
    GoogleDriveSavedSearch,
)
from app.schemas.drive_workspace import (
    DriveActivityResponse,
    DriveFolder,
    DriveInsights,
    DriveItemsResponse,
    PinnedLocation,
    PinnedLocationCreate,
    PinnedLocationList,
    SavedSearch,
    SavedSearchCreate,
    SavedSearchFilters,
    SavedSearchList,
    SyncAttemptList,
)
from app.schemas.integrations import GoogleDriveSummary
from app.schemas.search import DriveCatalogStatus
from app.services.drive_workspace import FOLDER_MIME_TYPE, DriveListFilters, DriveWorkspace

router = APIRouter(prefix="/integrations/google-drive", tags=["google-drive"])


@router.get("/connect")
def connect(
    principal: Annotated[Principal, Depends(require_principal)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    if not settings.google_is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Drive is not configured.",
        )
    session = db.get(AuthSession, principal.session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )
    state = secrets.token_urlsafe(32)
    session.oauth_state_hash = digest(state, settings.session_secret.get_secret_value())
    session.oauth_state_expires_at = datetime.now(UTC) + timedelta(minutes=10)
    db.commit()
    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_DRIVE_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return RedirectResponse(
        f"https://accounts.google.com/o/oauth2/v2/auth?{query}", status_code=302
    )


@router.get("/oauth/callback")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Annotated[Session, Depends(get_db_session)] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,
) -> RedirectResponse:
    if error or not code or not state or not settings.auth_is_configured:
        return RedirectResponse("/?google_drive=denied", status_code=303)
    session = get_session(db, settings, request.cookies.get(SESSION_COOKIE))
    if (
        session is None
        or _oauth_state_expired(session.oauth_state_expires_at)
        or session.oauth_state_hash is None
        or not secrets.compare_digest(
            session.oauth_state_hash, digest(state, settings.session_secret.get_secret_value())
        )
    ):
        return RedirectResponse("/?google_drive=invalid_state", status_code=303)
    session.oauth_state_hash = None
    session.oauth_state_expires_at = None
    db.commit()
    integration = GoogleDriveIntegration(settings, db)
    try:
        integration.exchange_code(session.principal_id, code)
    except GoogleDriveError:
        return RedirectResponse("/?google_drive=failed", status_code=303)
    try:
        integration.sync_catalog(session.principal_id)
    except GoogleDriveError:
        return RedirectResponse("/?google_drive=connected&catalog=failed", status_code=303)
    return RedirectResponse("/?google_drive=connected", status_code=303)


@router.get("/status", response_model=GoogleDriveSummary)
def google_drive_status(
    principal: Annotated[Principal, Depends(require_principal)],
    integration: Annotated[GoogleDriveIntegration, Depends(get_google_drive_integration)],
) -> GoogleDriveSummary:
    return integration.summary(principal.id)


@router.post("/refresh", response_model=GoogleDriveSummary)
def refresh_google_drive(
    principal: Annotated[Principal, Depends(require_csrf)],
    integration: Annotated[GoogleDriveIntegration, Depends(get_google_drive_integration)],
) -> GoogleDriveSummary:
    return integration.summary(principal.id, force_refresh=True)


@router.get("/catalog/status", response_model=DriveCatalogStatus)
def google_drive_catalog_status(
    principal: Annotated[Principal, Depends(require_principal)],
    integration: Annotated[GoogleDriveIntegration, Depends(get_google_drive_integration)],
) -> DriveCatalogStatus:
    return integration.catalog_status(principal.id)


@router.post("/catalog/sync", response_model=DriveCatalogStatus)
def sync_google_drive_catalog(
    principal: Annotated[Principal, Depends(require_csrf)],
    integration: Annotated[GoogleDriveIntegration, Depends(get_google_drive_integration)],
) -> DriveCatalogStatus:
    try:
        return integration.sync_catalog(principal.id)
    except ActiveGoogleDriveSyncError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except GoogleDriveError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_google_drive(
    principal: Annotated[Principal, Depends(require_csrf)],
    integration: Annotated[GoogleDriveIntegration, Depends(get_google_drive_integration)],
) -> None:
    integration.disconnect(principal.id)


@router.get("/items", response_model=DriveItemsResponse)
def drive_items(
    principal: Annotated[Principal, Depends(require_principal)],
    db: Annotated[Session, Depends(get_db_session)],
    integration: Annotated[GoogleDriveIntegration, Depends(get_google_drive_integration)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    view: Annotated[str, Query(pattern="^(all|recent|starred)$")] = "all",
    kind: Annotated[
        str, Query(pattern="^(all|folder|document|image|video|audio|archive|other)$")
    ] = "all",
    parent_id: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
    modified_after: AwareDatetime | None = None,
    modified_before: AwareDatetime | None = None,
    min_size: Annotated[int | None, Query(ge=0)] = None,
    max_size: Annotated[int | None, Query(ge=0)] = None,
    starred: bool | None = None,
    ownership: Annotated[str, Query(pattern="^owned_by_me$")] = "owned_by_me",
    sort: Annotated[str, Query(pattern="^(modified|created|name|size)$")] = "modified",
    direction: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> DriveItemsResponse:
    query = q.strip() if q is not None else None
    if q is not None and not query:
        raise HTTPException(status_code=422, detail="Query must not be blank.")
    if modified_after and modified_before and modified_after >= modified_before:
        raise HTTPException(
            status_code=422, detail="modified_after must be before modified_before."
        )
    if min_size is not None and max_size is not None and min_size > max_size:
        raise HTTPException(status_code=422, detail="min_size must not exceed max_size.")
    filters = DriveListFilters(
        q=query,
        view=view,
        kind=kind,
        parent_id=parent_id,
        modified_after=modified_after,
        modified_before=modified_before,
        min_size=min_size,
        max_size=max_size,
        starred=starred,
        ownership=ownership,
        sort=sort,
        direction=direction,
    )
    return DriveWorkspace(db).list_items(
        principal.id, filters, cursor, limit, integration.catalog_status(principal.id)
    )


@router.get("/folders/{folder_id}", response_model=DriveFolder)
def drive_folder(
    folder_id: str,
    principal: Annotated[Principal, Depends(require_principal)],
    db: Annotated[Session, Depends(get_db_session)],
) -> DriveFolder:
    return DriveWorkspace(db).folder(principal.id, folder_id)


@router.get("/saved-searches", response_model=SavedSearchList)
def saved_searches(
    principal: Annotated[Principal, Depends(require_principal)],
    db: Annotated[Session, Depends(get_db_session)],
) -> SavedSearchList:
    values = db.scalars(
        select(GoogleDriveSavedSearch)
        .where(GoogleDriveSavedSearch.principal_id == principal.id)
        .order_by(GoogleDriveSavedSearch.created_at.asc(), GoogleDriveSavedSearch.id.asc())
    )
    return SavedSearchList(items=[_saved_search_schema(value) for value in values])


@router.post("/saved-searches", response_model=SavedSearch, status_code=status.HTTP_201_CREATED)
def create_saved_search(
    payload: SavedSearchCreate,
    principal: Annotated[Principal, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db_session)],
) -> SavedSearch:
    _require_connection(db, principal.id)
    timestamp = datetime.now(UTC)
    value = GoogleDriveSavedSearch(
        id=str(uuid.uuid4()),
        principal_id=principal.id,
        name=payload.name,
        query=payload.q,
        view=payload.view,
        kind=payload.kind,
        parent_id=payload.parent_id,
        modified_after=payload.modified_after,
        modified_before=payload.modified_before,
        min_size=payload.min_size,
        max_size=payload.max_size,
        starred=payload.starred,
        ownership=payload.ownership,
        sort=payload.sort,
        direction=payload.direction,
        created_at=timestamp,
    )
    db.add(value)
    db.commit()
    return _saved_search_schema(value)


@router.delete("/saved-searches/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_search(
    search_id: str,
    principal: Annotated[Principal, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db_session)],
) -> None:
    value = db.scalar(
        select(GoogleDriveSavedSearch).where(
            GoogleDriveSavedSearch.id == search_id,
            GoogleDriveSavedSearch.principal_id == principal.id,
        )
    )
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved search not found.")
    db.delete(value)
    db.commit()


@router.get("/pinned-locations", response_model=PinnedLocationList)
def pinned_locations(
    principal: Annotated[Principal, Depends(require_principal)],
    db: Annotated[Session, Depends(get_db_session)],
) -> PinnedLocationList:
    return PinnedLocationList(items=DriveWorkspace(db).pins(principal.id))


@router.post(
    "/pinned-locations", response_model=PinnedLocation, status_code=status.HTTP_201_CREATED
)
def create_pinned_location(
    payload: PinnedLocationCreate,
    principal: Annotated[Principal, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db_session)],
) -> PinnedLocation:
    folder = db.get(GoogleDriveCatalogItem, (principal.id, payload.drive_folder_id))
    if folder is None or folder.mime_type != FOLDER_MIME_TYPE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found.")
    db.add(
        GoogleDrivePinnedLocation(
            id=str(uuid.uuid4()),
            principal_id=principal.id,
            drive_folder_id=payload.drive_folder_id,
            label=payload.label,
            created_at=datetime.now(UTC),
        )
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Folder is already pinned."
        ) from error
    return next(
        value
        for value in DriveWorkspace(db).pins(principal.id)
        if value.drive_folder_id == payload.drive_folder_id
    )


@router.delete("/pinned-locations/{pin_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pinned_location(
    pin_id: str,
    principal: Annotated[Principal, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db_session)],
) -> None:
    value = db.scalar(
        select(GoogleDrivePinnedLocation).where(
            GoogleDrivePinnedLocation.id == pin_id,
            GoogleDrivePinnedLocation.principal_id == principal.id,
        )
    )
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pinned location not found."
        )
    db.delete(value)
    db.commit()


@router.get("/insights", response_model=DriveInsights)
def drive_insights(
    principal: Annotated[Principal, Depends(require_principal)],
    db: Annotated[Session, Depends(get_db_session)],
) -> DriveInsights:
    return DriveWorkspace(db).insights(principal.id)


@router.get("/catalog/syncs", response_model=SyncAttemptList)
def catalog_sync_history(
    principal: Annotated[Principal, Depends(require_principal)],
    db: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SyncAttemptList:
    return DriveWorkspace(db).sync_history(principal.id, limit)


@router.get("/activity", response_model=DriveActivityResponse)
def drive_activity(
    principal: Annotated[Principal, Depends(require_principal)],
    db: Annotated[Session, Depends(get_db_session)],
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> DriveActivityResponse:
    return DriveWorkspace(db).activity(principal.id, cursor, limit)


def _oauth_state_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at < datetime.now(UTC)


def _require_connection(db: Session, principal_id: str) -> None:
    if db.get(GoogleDriveConnection, principal_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drive not connected.")


def _saved_search_schema(value: GoogleDriveSavedSearch) -> SavedSearch:
    return SavedSearch(
        id=value.id,
        name=value.name,
        filters=SavedSearchFilters(
            q=value.query,
            view=value.view,  # type: ignore[arg-type]
            kind=value.kind,  # type: ignore[arg-type]
            parent_id=value.parent_id,
            modified_after=_as_utc(value.modified_after),
            modified_before=_as_utc(value.modified_before),
            min_size=value.min_size,
            max_size=value.max_size,
            starred=value.starred,
            ownership=value.ownership,  # type: ignore[arg-type]
            sort=value.sort,  # type: ignore[arg-type]
            direction=value.direction,  # type: ignore[arg-type]
        ),
        created_at=value.created_at,
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
