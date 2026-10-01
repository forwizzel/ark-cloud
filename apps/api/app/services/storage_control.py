"""Persistent application policy; host configuration remains the mount authority."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import SessionLocal
from app.models import StorageControl


def control(db: Session) -> StorageControl:
    if db.bind.dialect.name == "postgresql":
        # Includes first-row creation, enrollment, claims and configuration writes.
        db.execute(select(func.pg_advisory_xact_lock(734019)))
    value = db.get(StorageControl, 1)
    if value is None:
        value = StorageControl(id=1, snapshot={}, blocked_roots=[])
        db.add(value)
        db.flush()
    return value


def upload_limit(settings: Settings) -> int:
    with SessionLocal() as db:
        value = db.get(StorageControl, 1)
        return (
            value.upload_max_bytes
            if value is not None and value.upload_max_bytes is not None
            else settings.storage_upload_max_bytes
        )


def blocked_roots() -> set[str]:
    with SessionLocal() as db:
        value = db.get(StorageControl, 1)
        return set(value.blocked_roots) if value else set()
