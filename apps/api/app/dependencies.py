from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.service import SESSION_COOKIE, Principal, get_session, validate_csrf
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.integrations.google_drive import GoogleDriveIntegration
from app.integrations.system import SystemIntegration
from app.integrations.tailscale import TailscaleIntegration
from app.models import LocalUser


def get_system_integration(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SystemIntegration:
    return SystemIntegration(settings)


def get_tailscale_integration(
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db_session)],
) -> TailscaleIntegration:
    from app.services.tailscale_control import runtime_integration

    return runtime_integration(db, settings)


def get_google_drive_integration(
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db_session)],
) -> GoogleDriveIntegration:
    return GoogleDriveIntegration(settings, db)


def get_optional_principal(
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal | None:
    session = get_session(db, settings, request.cookies.get(SESSION_COOKIE))
    if session is None:
        return None
    user = db.get(LocalUser, session.principal_id)
    if user is None or not user.active or user.password_hash is None:
        return None
    return Principal(id=user.id, username=user.username, session_id=session.id, role=user.role)


def require_principal(
    principal: Annotated[Principal | None, Depends(get_optional_principal)],
) -> Principal:
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )
    return principal


def require_csrf(
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    session = get_session(db, settings, request.cookies.get(SESSION_COOKIE))
    if session is None or not validate_csrf(
        db, settings, session, request.headers.get("X-CSRF-Token")
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed.")
    return principal


def require_admin(principal: Annotated[Principal, Depends(require_csrf)]) -> Principal:
    if principal.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator required.")
    return principal
