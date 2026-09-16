import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import AuthSession

SESSION_COOKIE = "ark_session"
CSRF_COOKIE = "ark_csrf"


@dataclass(frozen=True)
class Principal:
    id: str
    username: str
    session_id: str


def now() -> datetime:
    return datetime.now(UTC)


def digest(value: str, secret: str) -> str:
    return hmac.new(secret.encode(), value.encode(), sha256).hexdigest()


def create_session(db: Session, settings: Settings) -> tuple[AuthSession, str, str]:
    if not settings.auth_is_configured:
        raise RuntimeError("Local authentication is not configured.")

    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    timestamp = now()
    session = AuthSession(
        id=str(uuid4()),
        principal_id=settings.auth_username or "",
        token_hash=digest(token, settings.session_secret.get_secret_value()),
        csrf_hash=digest(csrf_token, settings.session_secret.get_secret_value()),
        expires_at=timestamp + timedelta(seconds=settings.session_max_age_seconds),
        created_at=timestamp,
        last_used_at=timestamp,
    )
    db.add(session)
    db.commit()
    return session, token, csrf_token


def get_session(db: Session, settings: Settings, token: str | None) -> AuthSession | None:
    if not settings.auth_is_configured or not token:
        return None
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == digest(token, settings.session_secret.get_secret_value())
        )
    )
    if session is None or _as_utc(session.expires_at) <= now():
        return None
    return session


def verify_password(settings: Settings, password: str) -> bool:
    if not settings.auth_is_configured:
        return False
    try:
        return PasswordHasher().verify(settings.auth_password_hash.get_secret_value(), password)
    except InvalidHashError, VerificationError, VerifyMismatchError:
        return False


def validate_csrf(settings: Settings, session: AuthSession, csrf_token: str | None) -> bool:
    return bool(
        csrf_token
        and hmac.compare_digest(
            session.csrf_hash, digest(csrf_token, settings.session_secret.get_secret_value())
        )
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
