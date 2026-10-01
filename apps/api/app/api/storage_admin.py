"""Metadata-only administration and an authenticated, typed host-manager protocol."""

import os
import secrets
from contextlib import suppress
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.local_storage import StorageRoute
from app.auth.service import Principal, token_hash
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.dependencies import require_admin, require_csrf, require_principal
from app.models import LocalUser, StorageJob, StoragePreference
from app.services.local_storage import (
    LocalStorage,
    RootConfig,
    StorageError,
    filesystem_error,
    load_manifest,
    mount_points,
    parts,
    rename_exclusive,
)
from app.services.storage_control import control, upload_limit

router = APIRouter(tags=["storage-administration"], route_class=StorageRoute)
DB = Annotated[Session, Depends(get_db_session)]
Admin = Annotated[Principal, Depends(require_admin)]
Reader = Annotated[Principal, Depends(require_principal)]
Writer = Annotated[Principal, Depends(require_csrf)]
Config = Annotated[Settings, Depends(get_settings)]
ACTIVE = ("queued", "applying", "verifying")


def now():
    return datetime.now(UTC)


def online(value):
    return (
        value.token_hash is not None
        and value.last_seen_at is not None
        and (now() - value.last_seen_at.replace(tzinfo=UTC)).total_seconds() < 30
    )


def host_manager(db: DB, authorization: Annotated[str | None, Header()] = None):
    value = control(db)
    token = authorization.removeprefix("Bearer ") if authorization else ""
    if not value.token_hash or not secrets.compare_digest(value.token_hash, token_hash(token)):
        raise HTTPException(401, "Host-manager authentication required.")
    return value


Manager = Annotated[object, Depends(host_manager)]


class Policy(BaseModel):
    upload_max_bytes: int | None = Field(default=None, ge=1, le=10 * 1024**3)


class Preference(BaseModel):
    root_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,39}$")
    path: str = Field(default="", max_length=2048)


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "add",
        "init",
        "update",
        "remove",
        "refresh-identity",
        "check",
        "browse",
        "preflight",
        "relocate",
    ]
    root_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,39}$")
    path: str = Field(default="", max_length=4096)
    label: str = Field(default="", max_length=80)
    owner: str | None = Field(default=None, max_length=36)
    read_only: bool = False
    selinux: Literal["preserve", "private", "shared"] = "preserve"
    confirmed: bool = False
    managed: bool = False
    grant_access: bool = False


class HostRoot(RootConfig):
    source: str = Field(max_length=4096)
    selinux: Literal["preserve", "private", "shared"]


class ApprovedArea(BaseModel):
    path: str = Field(max_length=4096)
    state: Literal["ready", "missing", "unavailable"]
    message: str = Field(max_length=2000)


class Report(BaseModel):
    roots: list[HostRoot] = Field(max_length=32)
    approved_paths: list[str] = Field(max_length=32)
    generation: str = Field(max_length=64)
    job_id: str | None = None
    state: Literal["applying", "verifying", "completed", "failed"] | None = None
    message: str = Field(default="", max_length=2000)
    result: dict = Field(default_factory=dict)
    approved_areas: list[ApprovedArea] = Field(default_factory=list, max_length=32)
    repository_path: str = Field(default="", max_length=4096)
    default_path: str = Field(default="", max_length=4096)


def job_view(job):
    return {
        key: getattr(job, key)
        for key in (
            "id",
            "action",
            "payload",
            "state",
            "message",
            "result",
            "created_at",
            "updated_at",
        )
    }


def recipient_available(job, db):
    owner = job.payload.get("owner")
    if job.action not in {"add", "update"} or not owner:
        return True
    user = db.get(LocalUser, owner)
    return user is not None and user.active


def job_presentation(
    job, value, db, *, configuration_error=None, busy=False, manifest=None, mounts=None
):
    view = job_view(job)
    root = next(
        (r for r in value.snapshot.get("roots", []) if r["id"] == job.payload.get("root_id")),
        None,
    )
    disposition = "current" if job.state in ACTIVE else "history"
    reason = None
    if job.state not in ACTIVE and job.result.get("dismissed_at"):
        disposition = "dismissed"
    if job.state == "failed":
        if job.result.get("dismissed_at"):
            disposition = "dismissed"
        elif job.result.get("canceled") or job.message == "Canceled before deployment.":
            disposition = "canceled"
        elif job.result.get("superseded_by"):
            disposition = "superseded"
        elif job.result.get("resolved"):
            disposition = "resolved"
        elif (
            job.action in {"update", "remove", "check", "refresh-identity", "relocate"}
            and not root
            and manifest is not None
            and not any(r.id == job.payload.get("root_id") for r in manifest.roots)
            and f"/srv/ark-storage/{job.payload.get('root_id')}" not in (mounts or set())
        ):
            disposition = "obsolete"
        else:
            disposition = "attention"
        if disposition != "attention":
            reason = "This request is historical and no longer applies."
        elif job.action == "setup":
            reason = "Run ./scripts/ark storage setup on the host to resume setup."
        elif not recipient_available(job, db):
            reason = "Choose an active account in Configure before trying again."
        elif job.action in {"add", "init"} and root and root["source"] != job.payload.get("path"):
            reason = "This location has changed. Configure its current settings instead."
        elif (
            job.action == "init"
            and not root
            and any(r["kind"] == "managed" for r in value.snapshot.get("roots", []))
        ):
            reason = "Private folders already have a base. Use Change base directory."
        elif configuration_error:
            reason = "Restore manifest access before retrying."
        elif not online(value):
            reason = "Reconnect the host helper before retrying."
        elif busy:
            reason = "Wait for the current storage operation to finish."
    view.update(
        disposition=disposition,
        can_retry=job.state == "failed" and reason is None,
        retry_reason=reason,
        can_dismiss=job.state not in ACTIVE and not job.result.get("dismissed_at"),
    )
    return view


def begin_setup(db, path, root_id):
    """Called only by the deployment-owner CLI, never a browser request."""
    value = control(db)
    db.execute(select(type(value)).where(type(value).id == 1).with_for_update())
    existing = db.scalar(select(StorageJob).where(StorageJob.state.in_(ACTIVE)))
    if existing:
        if existing.action == "setup" and existing.payload == {"path": path, "root_id": root_id}:
            return job_view(existing)
        raise ValueError("Finish the active storage operation before setup. No files were changed.")
    administrator = db.scalar(
        select(LocalUser)
        .where(LocalUser.active.is_(True), LocalUser.role == "admin")
        .order_by(LocalUser.created_at)
    )
    if administrator is None:
        raise ValueError("Create your first administrator in Ark before setting up Local Files.")
    job = StorageJob(
        id=str(uuid4()),
        principal_id=administrator.id,
        action="setup",
        payload={"path": path, "root_id": root_id},
        state="applying",
        message="Preparing host storage.",
        result={},
        created_at=now(),
        updated_at=now(),
    )
    value.blocked_roots = sorted(set(value.blocked_roots) | {root_id})
    db.add(job)
    db.commit()
    return job_view(job)


@router.get("/storage/preferences")
def preferences(principal: Reader, db: DB, settings: Config):
    value = db.get(StoragePreference, principal.id)
    return {
        "root_id": value.root_id if value else None,
        "path": value.path if value else "",
        "upload_max_bytes": upload_limit(settings),
    }


@router.put("/storage/preferences")
def save_preference(body: Preference, principal: Writer, db: DB, settings: Config):
    parts(body.path, allow_empty=True)
    if body.root_id:
        storage = LocalStorage(load_manifest(settings.storage_manifest))
        with storage.root(body.root_id, principal.id) as root, storage.directory(root, body.path):
            pass
    elif body.path:
        raise HTTPException(422, "Choose a storage location first.")
    value = db.get(StoragePreference, principal.id)
    if value is None:
        value = StoragePreference(principal_id=principal.id)
        db.add(value)
    value.root_id, value.path = body.root_id, body.path
    db.commit()
    return preferences(principal, db, settings)


@router.post("/storage/private-folder")
def create_private_folder(principal: Writer, settings: Config):
    storage = LocalStorage(load_manifest(settings.storage_manifest))
    managed = next((root for root in storage.manifest.roots if root.kind == "managed"), None)
    if managed is None:
        raise HTTPException(409, "Private account folders are not enabled.")
    with storage.root(managed.id, principal.id, provision=True):
        pass
    return {"message": "Your private folder is ready."}


@router.get("/admin/storage")
def inventory(principal: Admin, db: DB, settings: Config):
    value = control(db)
    db.commit()
    snapshot = value.snapshot
    try:
        manifest = load_manifest(settings.storage_manifest)
        configuration_error = None
    except StorageError:
        # The host inventory and job history are still useful for recovery.
        # Never treat an unreadable manifest as an empty, applied configuration.
        manifest = None
        configuration_error = (
            "The API cannot read or validate its storage manifest. "
            "Ask the host owner to check .ark-storage/manifest.json and its permissions."
        )
    users = db.scalars(select(LocalUser).order_by(LocalUser.username)).all()
    items = []
    for source in snapshot.get("roots", []):
        item = dict(source)
        owner = next((user for user in users if user.id == source.get("owner")), None)
        item["username"] = owner.username if owner else None
        item["state"], item["message"] = (
            "unavailable",
            configuration_error or "Configuration is not applied.",
        )
        config = (
            next((r for r in manifest.roots if r.id == source["id"]), None) if manifest else None
        )
        if config and config.model_dump() == {k: source[k] for k in config.model_dump()}:
            try:
                if config.kind == "assigned" and owner is None:
                    raise StorageError("The assigned account no longer exists.")
                service = LocalStorage(manifest, verification=True)
                with service.root(config.id, config.owner or principal.id, base=True) as fd:
                    os.fstatvfs(fd)
                    if not os.access(".", os.R_OK | os.X_OK, dir_fd=fd):
                        raise StorageError("Read access denied. Check permissions and SELinux.")
                    if not config.read_only and not os.access(".", os.W_OK | os.X_OK, dir_fd=fd):
                        raise StorageError("Write access denied. Check permissions and SELinux.")
                item["state"], item["message"] = "healthy", "Connected"
                if config.id in value.blocked_roots:
                    item["state"], item["message"] = (
                        "unavailable",
                        "Access paused until verification succeeds. Retry the failed operation.",
                    )
            except (StorageError, OSError) as error:
                item["message"] = str(
                    error if isinstance(error, StorageError) else filesystem_error(error)
                )
        items.append(item)
    recent = db.scalars(select(StorageJob).order_by(StorageJob.created_at.desc()).limit(30)).all()
    pending = db.scalars(select(StorageJob).where(StorageJob.state.in_((*ACTIVE, "failed")))).all()
    jobs = sorted(
        {j.id: j for j in [*recent, *pending]}.values(), key=lambda j: j.created_at, reverse=True
    )
    busy = any(j.state in ACTIVE for j in jobs)
    mounts = mount_points()
    setup_job = next((job for job in jobs if job.action == "setup"), None)
    return {
        "configuration_error": configuration_error,
        "manager": {
            "enrolled": bool(value.token_hash),
            "online": online(value),
            "last_seen_at": value.last_seen_at,
            "approved_paths": snapshot.get("approved_paths", []),
            "approved_areas": snapshot.get("approved_areas", []),
        },
        "setup": {
            "default_path": snapshot.get("default_path") or "~/Ark-Files",
            "repository_path": snapshot.get("repository_path") or None,
            "job": job_view(setup_job) if setup_job else None,
            "interrupted": bool(
                setup_job
                and setup_job.state in ACTIVE
                and (now() - setup_job.updated_at.replace(tzinfo=UTC)).total_seconds() > 300
            ),
        },
        "generation": snapshot.get("generation"),
        "roots": items,
        "jobs": [
            job_presentation(
                job,
                value,
                db,
                configuration_error=configuration_error,
                busy=busy,
                manifest=manifest,
                mounts=mounts,
            )
            for job in jobs
        ],
        "upload_max_bytes": upload_limit(settings),
        "upload_limit_source": "ui" if value.upload_max_bytes is not None else "environment",
        "users": [
            {
                "id": user.id,
                "username": user.username,
                "active": user.active,
                "pending": user.password_hash is None,
            }
            for user in users
        ],
    }


@router.put("/admin/storage/settings")
def policy(body: Policy, principal: Admin, db: DB):
    value = control(db)
    value.upload_max_bytes = body.upload_max_bytes
    db.add(
        StorageJob(
            id=str(uuid4()),
            principal_id=principal.id,
            action="settings",
            payload=body.model_dump(),
            state="completed",
            message="Upload policy saved.",
            result={},
            created_at=now(),
            updated_at=now(),
        )
    )
    db.commit()
    return {"message": "Upload policy saved. No restart needed."}


@router.post("/admin/storage/jobs", status_code=202)
def submit(body: Operation, principal: Admin, db: DB, settings: Config):
    value = control(db)
    # Serialize deployment mutations, including operations awaiting recovery.
    db.execute(select(type(value)).where(type(value).id == 1).with_for_update())
    if not online(value):
        raise HTTPException(
            409, "The host storage manager is offline. Reconnect it before making changes."
        )
    if db.scalar(select(StorageJob).where(StorageJob.state.in_(ACTIVE))):
        raise HTTPException(409, "Another storage operation is in progress.")
    roots = value.snapshot.get("roots", [])
    current = next((root for root in roots if root["id"] == body.root_id), None)
    if body.action in {"add", "init", "preflight"}:
        if not body.path.startswith("/") or not body.label.strip():
            raise HTTPException(422, "Choose an absolute host path and a location name.")
        if body.action == "init" and any(root["kind"] == "managed" for root in roots):
            raise HTTPException(
                409,
                "Private folders already have a base. "
                "Use Change base directory to copy and switch safely.",
            )
        if body.action != "init" and not (body.action == "preflight" and body.managed):
            user = db.get(LocalUser, body.owner) if body.owner else None
            if user is None or not user.active:
                raise HTTPException(422, "Choose an active account.")
    if body.action in {"remove", "update", "refresh-identity", "check"} and current is None:
        raise HTTPException(404, "Unknown storage location.")
    if body.action == "update":
        if not body.label.strip():
            raise HTTPException(422, "Enter a location name.")
        if current["kind"] == "assigned":
            user = db.get(LocalUser, body.owner) if body.owner else None
            if user is None or not user.active:
                raise HTTPException(422, "Choose an active account.")
    if body.action == "relocate" and (
        current is None or current["kind"] != "managed" or not body.path.startswith("/")
    ):
        raise HTTPException(422, "Choose a new absolute path for the existing private-folder base.")
    if body.action not in {"browse", "preflight", "check"} and not body.confirmed:
        raise HTTPException(422, "Review and confirm the storage change first.")
    if body.action in {"add", "init", "remove", "update", "refresh-identity", "relocate"}:
        load_manifest(settings.storage_manifest)
    if body.action == "add":
        body.root_id = "folder-" + uuid4().hex[:12]
    if body.action == "init":
        body.root_id = "personal"
    previously_blocked = body.root_id in value.blocked_roots
    if body.action in {"add", "init", "remove", "update", "refresh-identity", "relocate"}:
        value.blocked_roots = sorted(set(value.blocked_roots) | {body.root_id})
    job = StorageJob(
        id=str(uuid4()),
        principal_id=principal.id,
        action=body.action,
        payload={**body.model_dump(), "previously_blocked": previously_blocked},
        state="queued",
        message="Waiting for the host manager.",
        result={},
        created_at=now(),
        updated_at=now(),
    )
    db.add(job)
    db.commit()
    return job_view(job)


@router.post("/admin/storage/manager/revoke")
def revoke(principal: Admin, db: DB):
    value = control(db)
    if db.scalar(select(StorageJob).where(StorageJob.state.in_(ACTIVE))):
        raise HTTPException(
            409, "Finish the current storage operation before revoking the manager."
        )
    value.token_hash = None
    db.commit()
    return {"message": "Host manager revoked. Existing mounts are preserved."}


@router.post("/admin/storage/jobs/{job_id}/retry", status_code=202)
def retry(job_id: str, principal: Admin, db: DB, settings: Config):
    value = control(db)
    db.execute(select(type(value)).where(type(value).id == 1).with_for_update())
    job = db.get(StorageJob, job_id)
    if job is None or job.state != "failed":
        raise HTTPException(409, "Only a failed operation can be retried.")
    try:
        manifest = load_manifest(settings.storage_manifest)
        error = None
    except StorageError as failure:
        manifest = None
        error = str(failure)
    view = job_presentation(
        job,
        value,
        db,
        configuration_error=error,
        busy=bool(db.scalar(select(StorageJob).where(StorageJob.state.in_(ACTIVE)))),
        manifest=manifest,
        mounts=mount_points(),
    )
    if not view["can_retry"]:
        raise HTTPException(409, view["retry_reason"])
    replacement = StorageJob(
        id=str(uuid4()),
        principal_id=principal.id,
        action=job.action,
        payload={
            **job.payload,
            "resume_id": job.payload.get("resume_id", job.id),
            "previously_blocked": job.payload.get("root_id") in value.blocked_roots,
        },
        state="queued",
        message="Retry requested.",
        result={},
        created_at=now(),
        updated_at=now(),
    )
    if job.action in {"add", "init", "remove", "update", "refresh-identity", "relocate"}:
        value.blocked_roots = sorted(set(value.blocked_roots) | {job.payload["root_id"]})
    db.add(replacement)
    job.result = {**job.result, "superseded_by": replacement.id}
    db.commit()
    return job_view(replacement)


@router.post("/admin/storage/jobs/{job_id}/cancel")
def cancel(job_id: str, principal: Admin, db: DB):
    value = control(db)
    job = db.get(StorageJob, job_id)
    if job is None or job.state != "queued":
        raise HTTPException(409, "Only a request that has not started can be canceled.")
    job.state, job.message, job.updated_at = "failed", "Canceled before deployment.", now()
    job.result = {**job.result, "canceled": True}
    if not job.payload.get("previously_blocked"):
        value.blocked_roots = [
            root for root in value.blocked_roots if root != job.payload.get("root_id")
        ]
    db.commit()
    return job_view(job)


@router.post("/admin/storage/jobs/dismiss-history")
def dismiss_history(principal: Admin, db: DB, settings: Config):
    value = control(db)
    try:
        manifest = load_manifest(settings.storage_manifest)
    except StorageError:
        manifest = None
    mounts = mount_points()
    count = 0
    for job in db.scalars(select(StorageJob).where(StorageJob.state.not_in(ACTIVE))):
        view = job_presentation(job, value, db, manifest=manifest, mounts=mounts)
        if view["disposition"] not in {"attention", "dismissed"} and view["can_dismiss"]:
            job.result = {**job.result, "dismissed_at": now().isoformat()}
            count += 1
    db.commit()
    return {"message": f"Dismissed {count} historical records. Storage access is unchanged."}


@router.post("/admin/storage/jobs/{job_id}/dismiss")
def dismiss_job(job_id: str, principal: Admin, db: DB):
    control(db)
    job = db.get(StorageJob, job_id)
    if job is None:
        raise HTTPException(404, "Unknown storage operation.")
    if job.state in ACTIVE:
        raise HTTPException(409, "An in-progress operation cannot be dismissed.")
    job.result = {**job.result, "dismissed_at": now().isoformat()}
    db.commit()
    return {"message": "Notification dismissed. Storage access is unchanged."}


@router.get("/storage-manager/work")
def work(manager: Manager, db: DB):
    value = control(db)
    value.last_seen_at = now()
    job = db.scalar(
        select(StorageJob)
        .where(StorageJob.state.in_(ACTIVE), StorageJob.action != "setup")
        .order_by(StorageJob.created_at)
    )
    if job:
        user = db.get(LocalUser, job.principal_id)
        expired = (now() - job.created_at.replace(tzinfo=UTC)).total_seconds() > 3600
        recipient_valid = recipient_available(job, db)
        if (
            user is None
            or not user.active
            or user.role != "admin"
            or expired
            or not recipient_valid
        ):
            if job.state == "queued":
                job.state, job.message, job.updated_at = (
                    "failed",
                    "Assigned account is no longer active. Choose an active account."
                    if not recipient_valid
                    else "Request expired or its administrator no longer has access.",
                    now(),
                )
                if not job.payload.get("previously_blocked"):
                    value.blocked_roots = [
                        root for root in value.blocked_roots if root != job.payload.get("root_id")
                    ]
                job = None
            else:
                # Reconcile an already-started operation; never abandon partial deployment state.
                pass
    db.commit()
    return {"job": job_view(job) if job else None}


@router.post("/storage-manager/report")
def report(body: Report, manager: Manager, db: DB, settings: Config):
    value = control(db)
    value.snapshot = {
        "roots": [root.model_dump() for root in body.roots],
        "approved_paths": body.approved_paths,
        "generation": body.generation,
        "approved_areas": [area.model_dump() for area in body.approved_areas],
        "repository_path": body.repository_path,
        "default_path": body.default_path,
    }
    value.last_seen_at = now()
    if body.job_id:
        job = db.get(StorageJob, body.job_id)
        if job is None:
            raise HTTPException(404, "Unknown storage operation.")
        if job.state not in ACTIVE:
            db.commit()
            return {"message": "Result already recorded.", "accepted": False}
        if body.state is None:
            raise HTTPException(422, "Operation state required.")
        if job.state == "queued" and body.state == "applying":
            user = db.get(LocalUser, job.principal_id)
            if user is None or not user.active or user.role != "admin":
                raise HTTPException(403, "Requesting administrator no longer has access.")
            if not recipient_available(job, db):
                raise HTTPException(409, "The assigned account is no longer active.")
        if body.state == "completed" and job.action not in {"browse", "preflight"}:
            if not recipient_available(job, db):
                raise HTTPException(409, "The assigned account is no longer active.")
            manifest = load_manifest(settings.storage_manifest)
            expected = [
                RootConfig.model_validate(
                    {k: v for k, v in r.model_dump().items() if k not in {"source", "selinux"}}
                )
                for r in body.roots
            ]
            if manifest.roots != expected:
                raise HTTPException(
                    409, "The running API has not loaded the new mount configuration yet."
                )
            # Verify mounts independently of the manager's claimed success; allow revoked
            # roots only inside this check, restoring revocation on any failure.
            try:
                service = LocalStorage(manifest, verification=True)
                configs = [r for r in manifest.roots if r.id == job.payload.get("root_id")]
                if job.action == "remove" and configs:
                    raise StorageError("The disconnected location is still mounted.")
                if (
                    job.action == "remove"
                    and f"/srv/ark-storage/{job.payload.get('root_id')}" in mount_points()
                ):
                    raise StorageError("The disconnected location is still mounted.")
                if job.action != "remove" and not configs:
                    raise StorageError("The requested location is not mounted.")
                for config in configs:
                    if job.action == "setup":
                        source = next(r for r in body.roots if r.id == config.id)
                        if config.kind != "managed" or source.source != job.payload["path"]:
                            raise StorageError(
                                "The applied private-folder base differs from setup."
                            )
                    if (
                        job.action in {"add", "update"}
                        and config.kind == "assigned"
                        and (
                            config.owner != job.payload.get("owner")
                            or config.read_only != job.payload.get("read_only")
                        )
                    ):
                        raise StorageError(
                            "The applied account assignment or access mode differs "
                            "from the request."
                        )
                    owner = config.owner or job.principal_id
                    with service.root(config.id, owner, base=True) as fd:
                        if not os.access(".", os.R_OK | os.X_OK, dir_fd=fd):
                            raise StorageError("The API cannot read this directory.")
                        if not config.read_only and not os.access(
                            ".", os.W_OK | os.X_OK, dir_fd=fd
                        ):
                            raise StorageError(
                                "The API cannot write to this directory. "
                                "Check permissions and SELinux."
                            )
                    if config.kind == "managed":
                        for user in db.scalars(select(LocalUser).where(LocalUser.active.is_(True))):
                            with service.root(config.id, user.id, provision=True):
                                pass
                    if not config.read_only:
                        with service.root(config.id, owner, write=True) as fd:
                            name = ".ark-probe-" + secrets.token_hex(8)
                            try:
                                target = os.open(
                                    name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=fd
                                )
                                os.close(target)
                                rename_exclusive(fd, name, fd, name + "-moved")
                            finally:
                                for candidate in (name, name + "-moved"):
                                    with suppress(FileNotFoundError):
                                        os.unlink(candidate, dir_fd=fd)
            except StorageError, OSError:
                raise
            value.blocked_roots = [
                root for root in value.blocked_roots if root != job.payload.get("root_id")
            ]
            for previous in db.scalars(
                select(StorageJob).where(
                    StorageJob.state == "failed", StorageJob.created_at < job.created_at
                )
            ):
                if previous.payload.get("root_id") == job.payload.get("root_id"):
                    previous.result = {**previous.result, "resolved": True}
        job.state, job.message, job.result, job.updated_at = (
            body.state,
            body.message,
            body.result,
            now(),
        )
    db.commit()
    return {"message": "Host configuration recorded.", "accepted": True}


@router.post("/storage-manager/reconcile")
def reconcile(body: Report, manager: Manager, db: DB, settings: Config):
    """The idle host helper calls this only after reconciling its durable journal."""
    value = control(db)
    if db.scalar(select(StorageJob).where(StorageJob.state.in_(ACTIVE))):
        raise HTTPException(
            409, "Finish the active operation before reconciling removed locations."
        )
    manifest = load_manifest(settings.storage_manifest)
    expected = [
        RootConfig.model_validate(
            {k: v for k, v in r.model_dump().items() if k not in {"source", "selinux"}}
        )
        for r in body.roots
    ]
    if manifest.roots != expected:
        raise HTTPException(409, "The API manifest does not match the host configuration.")
    present = {root.id for root in manifest.roots}
    mounts = mount_points()
    removed = {
        root
        for root in value.blocked_roots
        if root not in present and f"/srv/ark-storage/{root}" not in mounts
    }
    value.blocked_roots = [root for root in value.blocked_roots if root not in removed]
    for job in db.scalars(select(StorageJob).where(StorageJob.state == "failed")):
        if job.action == "remove" and job.payload.get("root_id") in removed:
            job.result = {**job.result, "resolved": True}
    db.commit()
    return {"message": "Removed locations reconciled. Existing storage permissions are unchanged."}
