import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.service import SESSION_COOKIE, Principal, digest, get_session
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.dependencies import get_google_drive_integration, require_csrf, require_principal
from app.integrations.google_drive import (
    GOOGLE_DRIVE_SCOPE,
    GoogleDriveError,
    GoogleDriveIntegration,
)
from app.models import AuthSession
from app.schemas.integrations import GoogleDriveSummary

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
        or session.oauth_state_expires_at is None
        or session.oauth_state_expires_at < datetime.now(UTC)
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


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_google_drive(
    principal: Annotated[Principal, Depends(require_csrf)],
    integration: Annotated[GoogleDriveIntegration, Depends(get_google_drive_integration)],
) -> None:
    integration.disconnect(principal.id)
