"""Persistent application policy; host configuration remains the mount authority."""

import time
from datetime import UTC, datetime

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


def host_health_error(root, deployed=None, *, db=None):
    """A retained bind is not evidence that its host source still exists."""
    if db is not None:
        return _host_health_error(db.get(StorageControl, 1), root, deployed)
    with SessionLocal() as db:
        return _host_health_error(db.get(StorageControl, 1), root, deployed)


def _host_health_error(value, root, deployed):
    if value and "root_health" in value.snapshot:
        source = next((r for r in value.snapshot.get("roots", []) if r["id"] == root.id), None)
        if source and all(source.get(k) == v for k, v in root.model_dump().items()):
            if (
                value.last_seen_at is None
                or (datetime.now(UTC) - value.last_seen_at.replace(tzinfo=UTC)).total_seconds()
                >= 30
            ):
                return (
                    "Host storage status is stale. "
                    "The storage manager must verify this location before use."
                )
            health = value.snapshot["root_health"].get(root.id)
            if not health:
                return "Host storage status could not be verified."
            return None if health["state"] == "ready" else health["message"]
    if deployed and deployed.state != "ready":
        return deployed.message
    return None


def wait_for_host_refresh(timeout=7):
    """Wait for the manager's next read-only scan without holding a DB lock."""
    started = datetime.now(UTC)
    deadline = time.monotonic() + timeout
    while True:
        with SessionLocal() as db:
            value = db.get(StorageControl, 1)
            if value is None or value.token_hash is None:
                return
            if value.last_seen_at and value.last_seen_at.replace(tzinfo=UTC) > started:
                return
        if time.monotonic() >= deadline:
            from app.services.local_storage import StorageError

            raise StorageError(
                "Host storage refresh timed out. Check the storage manager and retry.", 503
            )
        time.sleep(0.1)
