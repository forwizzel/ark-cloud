from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


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
    oauth_state_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    oauth_state_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GoogleDriveConnection(Base):
    __tablename__ = "google_drive_connections"

    principal_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("local_users.id", ondelete="CASCADE"), primary_key=True
    )
    account_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    account_name: Mapped[str | None] = mapped_column(String(320), nullable=True)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text)
    granted_scopes: Mapped[str] = mapped_column(Text)
    catalog_generation: Mapped[str | None] = mapped_column(String(36), nullable=True)
    root_folder_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    used_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoogleDriveCatalogSync(Base):
    __tablename__ = "google_drive_catalog_syncs"

    principal_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("google_drive_connections.principal_id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    change_page_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    catalog_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phase: Mapped[str | None] = mapped_column(String(32), nullable=True)
    processed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    recovery: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoogleDriveCatalogItem(Base):
    __tablename__ = "google_drive_catalog_items"
    __table_args__ = (
        UniqueConstraint("principal_id", "drive_file_id", name="uq_drive_catalog_principal_file"),
        Index(
            "ix_drive_catalog_principal_modified",
            "principal_id",
            "drive_modified_at",
            "drive_file_id",
        ),
        Index("ix_drive_catalog_principal_starred", "principal_id", "starred", "drive_file_id"),
    )

    principal_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("google_drive_connections.principal_id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    drive_file_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    name_search: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    drive_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    drive_modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    web_url: Mapped[str] = mapped_column(Text)
    parent_ids: Mapped[list[str]] = mapped_column(JSON)
    starred: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    owned_by_me: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoogleDriveParentEdge(Base):
    __tablename__ = "google_drive_parent_edges"
    __table_args__ = (
        Index(
            "ix_drive_parent_principal_parent",
            "principal_id",
            "parent_file_id",
            "child_file_id",
        ),
    )

    principal_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("google_drive_connections.principal_id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    child_file_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    parent_file_id: Mapped[str] = mapped_column(String(256), primary_key=True)


class GoogleDriveSavedSearch(Base):
    __tablename__ = "google_drive_saved_searches"
    __table_args__ = (
        Index("ix_drive_saved_search_principal_created", "principal_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    principal_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("google_drive_connections.principal_id", ondelete="CASCADE", onupdate="CASCADE"),
    )
    name: Mapped[str] = mapped_column(String(100))
    query: Mapped[str | None] = mapped_column(String(200), nullable=True)
    view: Mapped[str] = mapped_column(String(16), default="all", server_default="all")
    kind: Mapped[str] = mapped_column(String(16), default="all", server_default="all")
    parent_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    modified_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    modified_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    min_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    starred: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ownership: Mapped[str] = mapped_column(
        String(16), default="owned_by_me", server_default="owned_by_me"
    )
    sort: Mapped[str] = mapped_column(String(16), default="modified", server_default="modified")
    direction: Mapped[str] = mapped_column(String(4), default="desc", server_default="desc")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoogleDrivePinnedLocation(Base):
    __tablename__ = "google_drive_pinned_locations"
    __table_args__ = (
        UniqueConstraint("principal_id", "drive_folder_id", name="uq_drive_pin_principal_folder"),
        Index("ix_drive_pin_principal_created", "principal_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    principal_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("google_drive_connections.principal_id", ondelete="CASCADE", onupdate="CASCADE"),
    )
    drive_folder_id: Mapped[str] = mapped_column(String(256))
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoogleDriveSyncAttempt(Base):
    __tablename__ = "google_drive_sync_attempts"
    __table_args__ = (
        Index("ix_drive_attempt_principal_started", "principal_id", "started_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    principal_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("google_drive_connections.principal_id", ondelete="CASCADE", onupdate="CASCADE"),
    )
    mode: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    phase: Mapped[str] = mapped_column(String(32))
    processed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    recovery: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GoogleDriveActivity(Base):
    __tablename__ = "google_drive_activities"
    __table_args__ = (
        Index("ix_drive_activity_principal_observed", "principal_id", "observed_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    principal_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("google_drive_connections.principal_id", ondelete="CASCADE", onupdate="CASCADE"),
    )
    event_type: Mapped[str] = mapped_column(String(32))
    drive_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    summary: Mapped[str] = mapped_column(String(500))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
