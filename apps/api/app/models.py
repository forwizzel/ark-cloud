from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TailscaleControl(Base):
    __tablename__ = "tailscale_control"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    configured_override: Mapped[bool] = mapped_column(Boolean, default=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    tailnet: Mapped[str] = mapped_column(String(320), default="-")
    desired_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    disconnect: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    principal_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    integration_state: Mapped[str] = mapped_column(String(32), default="not_configured")
    integration_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    integration_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    auth_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_key_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    auth_key_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StorageControl(Base):
    __tablename__ = "storage_control"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    upload_max_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    blocked_roots: Mapped[list] = mapped_column(JSON, default=list)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StorageJob(Base):
    __tablename__ = "storage_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StoragePreference(Base):
    __tablename__ = "storage_preferences"

    principal_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("local_users.id", ondelete="CASCADE"), primary_key=True
    )
    root_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    path: Mapped[str] = mapped_column(String(2048), default="")


class StorageLocation(Base):
    __tablename__ = "storage_locations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    root_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    retired: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=0)


class StorageGrant(Base):
    __tablename__ = "storage_grants"

    location_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("storage_locations.id", ondelete="CASCADE"), primary_key=True
    )
    principal_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("local_users.id", ondelete="CASCADE"), primary_key=True
    )
    level: Mapped[str] = mapped_column(String(8))
    version: Mapped[str] = mapped_column(String(36))


class LocalUser(Base):
    __tablename__ = "local_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    invite_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    invite_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BootstrapCode(Base):
    __tablename__ = "bootstrap_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LocalSessionKey(Base):
    __tablename__ = "local_session_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    secret: Mapped[str] = mapped_column(String(128))


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    principal_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("local_users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
