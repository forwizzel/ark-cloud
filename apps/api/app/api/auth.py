from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.service import CSRF_COOKIE, SESSION_COOKIE, Principal, create_session, verify_password
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.dependencies import get_optional_principal, require_csrf
from app.schemas.auth import LoginRequest, SessionResponse

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/session", response_model=SessionResponse)
def session_status(
    request: Request,
    principal: Annotated[Principal | None, Depends(get_optional_principal)],
) -> SessionResponse:
    if principal is None:
        return SessionResponse(authenticated=False)
    return SessionResponse(
        authenticated=True,
        username=principal.username,
        csrf_token=request.cookies.get(CSRF_COOKIE),
    )


@router.post("/login", response_model=SessionResponse)
def login(
    credentials: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionResponse:
    if not settings.auth_is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        )
    if credentials.username != settings.auth_username or not verify_password(
        settings, credentials.password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password."
        )

    _, token, csrf_token = create_session(db, settings)
    cookie_options = {
        "max_age": settings.session_max_age_seconds,
        "secure": settings.cookie_secure,
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **cookie_options)
    response.set_cookie(CSRF_COOKIE, csrf_token, httponly=False, **cookie_options)
    return SessionResponse(
        authenticated=True, username=settings.auth_username, csrf_token=csrf_token
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    _: Annotated[Principal, Depends(require_csrf)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> None:
    from app.auth.service import get_session

    session = get_session(db, settings, request.cookies.get(SESSION_COOKIE))
    if session is not None:
        db.delete(session)
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
