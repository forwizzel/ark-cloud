from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.auth.service import Principal
from app.core.database import get_db_session
from app.dependencies import get_google_drive_integration, require_principal
from app.integrations.google_drive import GoogleDriveIntegration
from app.schemas.search import SearchResponse
from app.services.drive_workspace import DriveListFilters, DriveWorkspace

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
def search(
    principal: Annotated[Principal, Depends(require_principal)],
    db: Annotated[Session, Depends(get_db_session)],
    drive: Annotated[GoogleDriveIntegration, Depends(get_google_drive_integration)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    kind: Annotated[
        str,
        Query(pattern="^(all|folder|document|image|video|audio|archive|other)$"),
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
) -> SearchResponse:
    query_text = q.strip()
    if not query_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Search query must not be blank.",
        )
    if modified_after and modified_before and modified_after >= modified_before:
        raise HTTPException(
            status_code=422, detail="modified_after must be before modified_before."
        )
    if min_size is not None and max_size is not None and min_size > max_size:
        raise HTTPException(status_code=422, detail="min_size must not exceed max_size.")
    result = DriveWorkspace(db).list_items(
        principal.id,
        DriveListFilters(
            q=query_text,
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
        ),
        cursor,
        limit,
        drive.catalog_status(principal.id),
    )
    return SearchResponse(
        items=result.items,
        next_cursor=result.next_cursor,
        catalog=result.catalog,
    )
