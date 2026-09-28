import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from re import fullmatch
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import AuthSession, LocalSessionKey, LocalUser, LoginAttempt

SESSION_COOKIE = "ark_session"
CSRF_COOKIE = "ark_csrf"
UNKNOWN_USER_HASH = PasswordHasher().hash(secrets.token_urlsafe(32))


@dataclass(frozen=True)
class Principal:
    id: str
    username: str
    session_id: str
    role: str = "member"


def now() -> datetime:
    return datetime.now(UTC)


def digest(value: str, secret: str) -> str:
    return hmac.new(secret.encode(), value.encode(), sha256).hexdigest()


def session_secret(db: Session, settings: Settings) -> str:
    if settings.session_secret and settings.session_secret.get_secret_value():
        return settings.session_secret.get_secret_value()
    key = db.get(LocalSessionKey, 1)
    if key is None:
        key = LocalSessionKey(id=1, secret=secrets.token_urlsafe(48))
        db.add(key)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            key = db.get(LocalSessionKey, 1)
    return key.secret


def create_session(
    db: Session, settings: Settings, user: LocalUser
) -> tuple[AuthSession, str, str]:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    timestamp = now()
    session = AuthSession(
        id=str(uuid4()),
        principal_id=user.id,
        token_hash=digest(token, session_secret(db, settings)),
        csrf_hash=digest(csrf_token, session_secret(db, settings)),
        expires_at=timestamp + timedelta(seconds=settings.session_max_age_seconds),
        created_at=timestamp,
        last_used_at=timestamp,
    )
    db.add(session)
    db.commit()
    return session, token, csrf_token


def get_session(db: Session, settings: Settings, token: str | None) -> AuthSession | None:
    if not token:
        return None
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == digest(token, session_secret(db, settings))
        )
    )
    if session is None or _as_utc(session.expires_at) <= now():
        return None
    return session


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return PasswordHasher().verify(password_hash, password)
    except InvalidHashError, VerificationError, VerifyMismatchError:
        return False


def normalize_username(username: str) -> str:
    value = username.strip().casefold()
    if not fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", value):
        raise ValueError("Username must be 3–64 letters, numbers, dots, dashes or underscores.")
    return value


def validate_new_password(password: str) -> None:
    if not 12 <= len(password) <= 1024:
        raise ValueError("Password must be between 12 and 1024 characters.")


def token_hash(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def throttle_key(db: Session, settings: Settings, action: str, subject: str) -> str:
    return digest(f"{action}:{subject}", session_secret(db, settings))


def throttled(db: Session, key: str) -> bool:
    attempt = db.get(LoginAttempt, key)
    return bool(
        attempt
        and attempt.failures >= 8
        and _as_utc(attempt.window_started_at) + timedelta(minutes=15) > now()
    )


def record_failure(db: Session, key: str) -> None:
    timestamp = now()
    db.execute(
        delete(LoginAttempt).where(LoginAttempt.window_started_at < timestamp - timedelta(days=1))
    )
    expired = LoginAttempt.window_started_at <= timestamp - timedelta(minutes=15)
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    statement = insert(LoginAttempt).values(id=key, failures=1, window_started_at=timestamp)
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[LoginAttempt.id],
            set_={
                "failures": case((expired, 1), else_=LoginAttempt.failures + 1),
                "window_started_at": case(
                    (expired, timestamp), else_=LoginAttempt.window_started_at
                ),
            },
        )
    )
    db.commit()


def clear_failure(db: Session, key: str) -> None:
    attempt = db.get(LoginAttempt, key)
    if attempt:
        db.delete(attempt)
        db.commit()


def validate_csrf(
    db: Session, settings: Settings, session: AuthSession, csrf_token: str | None
) -> bool:
    return bool(
        csrf_token
        and hmac.compare_digest(session.csrf_hash, digest(csrf_token, session_secret(db, settings)))
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
