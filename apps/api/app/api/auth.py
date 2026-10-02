import secrets
from datetime import timedelta
from typing import Annotated
from uuid import uuid4

from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.service import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    UNKNOWN_USER_HASH,
    Principal,
    clear_failure,
    create_session,
    normalize_username,
    now,
    record_failure,
    throttle_key,
    throttled,
    token_hash,
    validate_new_password,
    verify_password,
)
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.dependencies import get_optional_principal, require_admin, require_csrf, require_principal
from app.models import (
    AuthSession,
    BootstrapCode,
    LocalUser,
    TailscaleControl,
)
from app.schemas.auth import (
    InviteRequest,
    LoginRequest,
    PasswordChange,
    RedeemRequest,
    SessionResponse,
    SetupRequest,
    UserChange,
    UserDelete,
    UsernameChange,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _user_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(LocalUser)) or 0


def _name(username: str) -> str:
    try:
        return normalize_username(username)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _password(password: str) -> None:
    try:
        validate_new_password(password)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _signed_out_request(request: Request) -> None:
    # Same-origin browser requests are allowed through the Vite proxy; cross-site form/fetch
    # requests must not exercise bootstrap or invitation redemption endpoints.
    if request.headers.get("sec-fetch-site") == "cross-site" or not request.headers.get(
        "content-type", ""
    ).startswith("application/json"):
        raise HTTPException(status_code=403, detail="Same-origin JSON request required.")


def _session_response(
    user: LocalUser, response: Response, db: Session, settings: Settings, request: Request
) -> SessionResponse:
    _, token, csrf_token = create_session(db, settings, user)
    cookie_options = {
        "max_age": settings.session_max_age_seconds,
        "secure": settings.cookie_secure or _managed_https_request(request, db),
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **cookie_options)
    response.set_cookie(CSRF_COOKIE, csrf_token, httponly=False, **cookie_options)
    return SessionResponse(
        authenticated=True, username=user.username, role=user.role, csrf_token=csrf_token
    )


def _managed_https_request(request: Request, db: Session) -> bool:
    # The private Serve gateway overwrites this header. Plain forwarded headers
    # supplied by clients must never determine authentication cookie policy.
    proof = request.headers.get("X-Ark-Remote-Access", "")
    if not proof:
        return False
    value = db.get(TailscaleControl, 1)
    return bool(
        value and value.token_hash and secrets.compare_digest(token_hash(proof), value.token_hash)
    )


def _revoke(db: Session, user_id: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.principal_id == user_id))


@router.get("/session", response_model=SessionResponse)
def session_status(
    request: Request,
    principal: Annotated[Principal | None, Depends(get_optional_principal)],
    db: Annotated[Session, Depends(get_db_session)],
) -> SessionResponse:
    if principal is None:
        return SessionResponse(authenticated=False, setup_required=_user_count(db) == 0)
    return SessionResponse(
        authenticated=True,
        username=principal.username,
        role=principal.role,
        csrf_token=request.cookies.get(CSRF_COOKIE),
    )


@router.post("/setup", response_model=SessionResponse)
def setup(
    credentials: SetupRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionResponse:
    _signed_out_request(request)
    username = _name(credentials.username)
    _password(credentials.password)
    key = throttle_key(db, settings, "setup", request.client.host if request.client else "unknown")
    if db.bind.dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(734017)))
    if _user_count(db):
        raise HTTPException(status_code=409, detail="Setup is already complete.")
    if throttled(db, key):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    code = db.get(BootstrapCode, 1)
    if (
        not code
        or code.expires_at.replace(tzinfo=code.expires_at.tzinfo or now().tzinfo) <= now()
        or not secrets.compare_digest(code.token_hash, token_hash(credentials.code))
    ):
        record_failure(db, key)
        raise HTTPException(status_code=403, detail="Invalid or expired setup code.")
    user = LocalUser(
        id=str(uuid4()),
        username=username,
        password_hash=PasswordHasher().hash(credentials.password),
        role="admin",
        active=True,
        created_at=now(),
        updated_at=now(),
    )
    db.add(user)
    db.delete(code)
    db.commit()
    clear_failure(db, key)
    return _session_response(user, response, db, settings, request)


@router.post("/login", response_model=SessionResponse)
def login(
    credentials: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionResponse:
    _signed_out_request(request)
    username = credentials.username.strip().casefold()
    key = throttle_key(
        db, settings, "login", f"{request.client.host if request.client else 'unknown'}:{username}"
    )
    if throttled(db, key):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    user = db.scalar(select(LocalUser).where(LocalUser.username == username))
    valid_password = verify_password(
        user.password_hash if user and user.active and user.password_hash else UNKNOWN_USER_HASH,
        credentials.password,
    )
    if not user or not user.active or not valid_password:
        record_failure(db, key)
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    clear_failure(db, key)
    return _session_response(user, response, db, settings, request)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    principal: Annotated[Principal, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db_session)],
) -> None:
    session = db.get(AuthSession, principal.session_id)
    if session is not None:
        db.delete(session)
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.put("/account/username", response_model=SessionResponse)
def change_username(
    payload: UsernameChange,
    principal: Annotated[Principal, Depends(require_csrf)],
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
) -> SessionResponse:
    user = db.get(LocalUser, principal.id)
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(status_code=403, detail="Current password is incorrect.")
    user.username = _name(payload.username)
    user.updated_at = now()
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username is already in use.") from error
    return SessionResponse(
        authenticated=True,
        username=user.username,
        role=user.role,
        csrf_token=request.cookies.get(CSRF_COOKIE),
    )


@router.put("/account/password", status_code=204)
def change_password(
    payload: PasswordChange,
    principal: Annotated[Principal, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db_session)],
) -> None:
    user = db.get(LocalUser, principal.id)
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(status_code=403, detail="Current password is incorrect.")
    _password(payload.new_password)
    user.password_hash = PasswordHasher().hash(payload.new_password)
    user.updated_at = now()
    _revoke(db, user.id)
    db.commit()


@router.get("/users")
def list_users(
    principal: Annotated[Principal, Depends(require_principal)],
    db: Annotated[Session, Depends(get_db_session)],
) -> list[dict]:
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator required.")
    return [
        {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "active": user.active,
            "pending": user.password_hash is None,
        }
        for user in db.scalars(select(LocalUser).order_by(LocalUser.username))
    ]


@router.post("/users", status_code=201)
def invite_user(
    payload: InviteRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    token = secrets.token_urlsafe(32)
    user = LocalUser(
        id=str(uuid4()),
        username=_name(payload.username),
        password_hash=None,
        role=payload.role,
        active=True,
        invite_hash=token_hash(token),
        invite_expires_at=now() + timedelta(hours=24),
        created_at=now(),
        updated_at=now(),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username is already in use.") from error
    return {"username": user.username, "token": token, "expires_in_hours": 24}


@router.post("/invite/redeem", response_model=SessionResponse)
def redeem_invite(
    payload: RedeemRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionResponse:
    _signed_out_request(request)
    _password(payload.password)
    key = throttle_key(db, settings, "invite", request.client.host if request.client else "unknown")
    if throttled(db, key):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    user = db.scalar(
        select(LocalUser)
        .where(LocalUser.invite_hash == token_hash(payload.token))
        .with_for_update()
    )
    if (
        not user
        or not user.active
        or user.password_hash
        or not user.invite_expires_at
        or user.invite_expires_at.replace(tzinfo=user.invite_expires_at.tzinfo or now().tzinfo)
        <= now()
    ):
        record_failure(db, key)
        raise HTTPException(status_code=403, detail="Invalid or expired invitation.")
    user.password_hash = PasswordHasher().hash(payload.password)
    user.invite_hash = None
    user.invite_expires_at = None
    user.updated_at = now()
    db.commit()
    clear_failure(db, key)
    return _session_response(user, response, db, settings, request)


@router.post("/users/{user_id}/invite")
def reissue_invite(
    user_id: str,
    principal: Annotated[Principal, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    user = db.get(LocalUser, user_id)
    if not user or not user.active or user.password_hash:
        raise HTTPException(status_code=404, detail="Pending invitation not found.")
    token = secrets.token_urlsafe(32)
    user.invite_hash = token_hash(token)
    user.invite_expires_at = now() + timedelta(hours=24)
    user.updated_at = now()
    db.commit()
    return {"username": user.username, "token": token, "expires_in_hours": 24}


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    payload: UserChange,
    principal: Annotated[Principal, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict:
    # Serializes last-admin checks, including concurrent demotions and deactivations.
    users = list(db.scalars(select(LocalUser).order_by(LocalUser.id).with_for_update()))
    user = next((value for value in users if value.id == user_id), None)
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    new_role = payload.role or user.role
    new_active = user.active if payload.active is None else payload.active
    if (
        user.role == "admin"
        and user.active
        and (new_role != "admin" or not new_active)
        and sum(
            value.role == "admin" and value.active and value.password_hash is not None
            for value in users
        )
        <= 1
    ):
        raise HTTPException(
            status_code=409, detail="The last active administrator cannot be removed."
        )
    role_changed = user.role != new_role
    user.role = new_role
    user.active = new_active
    user.updated_at = now()
    if not new_active or role_changed:
        _revoke(db, user.id)
    if not new_active:
        user.invite_hash = None
        user.invite_expires_at = None
    db.commit()
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "active": user.active,
        "pending": user.password_hash is None,
    }


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    payload: UserDelete,
    principal: Annotated[Principal, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> None:
    users = list(db.scalars(select(LocalUser).order_by(LocalUser.id).with_for_update()))
    user = next((value for value in users if value.id == user_id), None)
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    admin = next(value for value in users if value.id == principal.id)
    if not verify_password(admin.password_hash, payload.current_password):
        raise HTTPException(status_code=403, detail="Current password is incorrect.")
    if _name(payload.confirm_username) != user.username:
        raise HTTPException(status_code=422, detail="Username confirmation does not match.")
    if (
        user.role == "admin"
        and user.active
        and sum(
            value.role == "admin" and value.active and value.password_hash is not None
            for value in users
        )
        <= 1
    ):
        raise HTTPException(
            status_code=409, detail="The last active administrator cannot be removed."
        )
    # Database cascades delete that user's Drive metadata, encrypted connection and sessions.
    db.delete(user)
    db.commit()
