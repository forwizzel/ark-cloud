from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(128), index=True)
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

    principal_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    account_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    account_name: Mapped[str | None] = mapped_column(String(320), nullable=True)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text)
    granted_scopes: Mapped[str] = mapped_column(Text)
    catalog_generation: Mapped[str | None] = mapped_column(String(36), nullable=True)
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
        ForeignKey("google_drive_connections.principal_id", ondelete="CASCADE"),
        primary_key=True,
    )
    change_page_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
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
    )

    principal_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("google_drive_connections.principal_id", ondelete="CASCADE"),
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
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
