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
from app.models import LocalUser, StorageGrant, StorageJob, StoragePreference
from app.services.local_storage import (
    MUTATIONS,
    LocalStorage,
    RootConfig,
    StorageError,
    filesystem_error,
    load_manifest,
    mount_points,
    parts,
    rename_exclusive,
)
from app.services.storage_access import ensure_location, retire_missing
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


class AccountAccess(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(min_length=1, max_length=128)
    level: Literal["none", "read", "write"]


class AccessChange(AccountAccess):
    revision: int = Field(ge=0)
    registration: str = Field(min_length=36, max_length=36)


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
        "repair",
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
    shared: bool = False
    create_directory: bool = False
    grants: list[AccountAccess] | None = Field(default=None, max_length=1000)
    automatic_access: bool = True
    registration: str | None = Field(default=None, min_length=36, max_length=36)
    restore_grants: bool = False


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
    managed_area: str = Field(default="", max_length=4096)


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
    for grant in job.payload.get("grants") or []:
        user = db.get(LocalUser, grant["user_id"])
        if grant["level"] != "none" and (user is None or not user.active):
            return False
    owner = job.payload.get("owner")
    if job.action != "add" or not owner:
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
            job.action in {"update", "remove", "check", "refresh-identity", "relocate", "repair"}
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


def pending_connection(db, root):
    """Only failed initial connection intent, never a saved user's live grants."""
    for job in db.scalars(
        select(StorageJob)
        .where(StorageJob.state == "failed", StorageJob.action.in_(("add", "init", "repair")))
        .order_by(StorageJob.created_at.desc())
    ):
        if (
            job.payload.get("root_id") == root["id"]
            and job.payload.get("path") == root["source"]
            and job.payload.get("grants") is not None
            and not job.result.get("resolved")
        ):
            return job
    return None


def normalize_repair(body, current, value, db):
    if body.registration and body.registration != current.get("registration"):
        raise HTTPException(409, "This location changed. Reopen it before repairing.")
    intent = pending_connection(db, current) if current["id"] in value.blocked_roots else None
    body.action = "repair"
    body.root_id, body.path = current["id"], current["source"]
    body.label, body.owner = current["label"], current.get("owner")
    body.read_only, body.selinux = current["read_only"], current["selinux"]
    body.managed, body.shared = current["kind"] == "managed", current["kind"] == "shared"
    body.registration = current.get("registration")
    body.restore_grants = intent is not None
    selections = (
        (body.grants if body.grants is not None else intent.payload["grants"]) if intent else None
    )
    body.grants = (
        [AccountAccess.model_validate(item) for item in selections]
        if selections is not None
        else None
    )
    body.automatic_access, body.grant_access = True, False
    return body


def connected_now(root, value, settings, owner):
    if root["id"] in value.blocked_roots:
        return False
    try:
        manifest = load_manifest(settings.storage_manifest)
        config = next((item for item in manifest.roots if item.id == root["id"]), None)
        if config is None or config.model_dump() != {
            key: root.get(key) for key in config.model_dump()
        }:
            return False
        with LocalStorage(manifest, verification=True).root(config.id, owner, base=True) as fd:
            return os.access(".", os.R_OK | os.X_OK, dir_fd=fd) and (
                config.read_only
                or (
                    os.access(".", os.W_OK | os.X_OK, dir_fd=fd)
                    and not os.fstatvfs(fd).f_flag & os.ST_RDONLY
                )
            )
    except StorageError, OSError:
        return False


def begin_setup(db, path, root_id, kind="managed"):
    """Called only by the deployment-owner CLI, never a browser request."""
    value = control(db)
    db.execute(select(type(value)).where(type(value).id == 1).with_for_update())
    existing = db.scalar(select(StorageJob).where(StorageJob.state.in_(ACTIVE)))
    if existing:
        if (
            existing.action == "setup"
            and existing.payload.get("path") == path
            and existing.payload.get("root_id") == root_id
            and existing.payload.get("kind", "managed") == kind
        ):
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
        payload={"path": path, "root_id": root_id, "kind": kind},
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
    with MUTATIONS, storage.root(managed.id, principal.id, provision=True):
        pass
    return {"message": "Your private folder is ready."}


def access_root(root_id, value, settings):
    manifest = load_manifest(settings.storage_manifest)
    config = next((r for r in manifest.roots if r.id == root_id), None)
    source = next((r for r in value.snapshot.get("roots", []) if r["id"] == root_id), None)
    if config is None or source is None:
        raise HTTPException(404, "Storage location not found.")
    if config.model_dump() != {k: source.get(k) for k in config.model_dump()}:
        raise HTTPException(409, "Wait for this location's mount configuration to be verified.")
    return manifest, config


def access_view(db, value, settings, root_id):
    manifest, config = access_root(root_id, value, settings)
    location = ensure_location(db, config)
    if location.retired:
        raise HTTPException(409, "This storage registration has been disconnected.")
    grants = {
        g.principal_id: g
        for g in db.scalars(select(StorageGrant).where(StorageGrant.location_id == location.id))
    }
    accounts = []
    for user in db.scalars(select(LocalUser).order_by(LocalUser.username)):
        grant = grants.get(user.id)
        level = grant.level if grant else "none"
        effective = (
            "none"
            if not user.active or root_id in value.blocked_roots
            else ("read" if level != "none" and config.read_only else level)
        )
        ready, message = False, "No access" if level == "none" else "Access inactive"
        if root_id in value.blocked_roots:
            message = "Access paused while this location is configured"
        if effective != "none":
            try:
                with LocalStorage(manifest, verification=True).root(
                    config.id, user.id, base=config.kind != "managed"
                ):
                    pass
                ready, message = (
                    True,
                    "Private folder ready"
                    if config.kind == "managed"
                    else "Shared directory ready",
                )
            except (StorageError, OSError) as error:
                message = str(error if isinstance(error, StorageError) else filesystem_error(error))
        accounts.append(
            {
                "id": user.id,
                "username": user.username,
                "active": user.active,
                "pending": user.password_hash is None,
                "level": level,
                "effective_level": effective,
                "ready": ready,
                "message": message,
            }
        )
    return {
        "root_id": root_id,
        "registration": location.id,
        "kind": config.kind,
        "host_read_only": config.read_only,
        "revision": location.revision,
        "accounts": accounts,
    }


@router.get("/admin/storage/roots/{root_id}/access")
def read_access(root_id: str, principal: Admin, db: DB, settings: Config):
    value = control(db)
    result = access_view(db, value, settings, root_id)
    db.commit()
    return result


@router.put("/admin/storage/roots/{root_id}/access")
def change_access(root_id: str, body: AccessChange, principal: Admin, db: DB, settings: Config):
    with MUTATIONS:
        value = control(db)
        manifest, config = access_root(root_id, value, settings)
        location = ensure_location(db, config)
        if location.retired or root_id in value.blocked_roots:
            raise HTTPException(409, "Finish this location's configuration before changing access.")
        if db.scalar(select(StorageJob).where(StorageJob.state.in_(ACTIVE))):
            raise HTTPException(409, "Finish the current storage operation before changing access.")
        if body.registration != location.id or body.revision != location.revision:
            raise HTTPException(
                409, "Access changed. Reopen Manage access to review current permissions."
            )
        user = db.get(LocalUser, body.user_id)
        if user is None or (body.level != "none" and not user.active):
            raise HTTPException(
                422, "Choose an active account, or revoke a disabled account's access."
            )
        if body.level == "write" and config.read_only:
            raise HTTPException(422, "This host mount is read-only. It cannot grant write access.")
        grant = db.get(StorageGrant, (location.id, user.id))
        before = grant.level if grant else "none"
        if body.level != "none" and config.kind == "managed":
            # Explicit administrator action, not a status read. The target is
            # always the immutable account directory beneath the confined base.
            with LocalStorage(manifest, verification=True).root(config.id, user.id, provision=True):
                pass
        if body.level == "none":
            if grant:
                db.delete(grant)
        elif grant:
            grant.level, grant.version = body.level, str(uuid4())
        else:
            db.add(
                StorageGrant(
                    location_id=location.id,
                    principal_id=user.id,
                    level=body.level,
                    version=str(uuid4()),
                )
            )
        location.revision += 1
        db.add(
            StorageJob(
                id=str(uuid4()),
                principal_id=principal.id,
                action="access",
                payload={
                    "root_id": root_id,
                    "user_id": user.id,
                    "before": before,
                    "level": body.level,
                },
                state="completed",
                message=f"Access for {user.username}: {body.level}. Files were preserved.",
                result={},
                created_at=now(),
                updated_at=now(),
            )
        )
        db.flush()
        result = access_view(db, value, settings, root_id)
        db.commit()
        return result


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
        if config and config.model_dump() == {k: source.get(k) for k in config.model_dump()}:
            try:
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
        item["blocked"] = source["id"] in value.blocked_roots
        intent = pending_connection(db, source) if item["blocked"] else None
        item["pending_grants"] = intent.payload.get("grants") if intent else None
        item["connection_state"] = "connected" if item["state"] == "healthy" else "needs_repair"
        relevant = db.scalars(select(StorageJob).where(StorageJob.state.in_(ACTIVE))).all()
        for job in relevant:
            if job.payload.get("root_id") == source["id"]:
                item["connection_state"] = "verifying" if job.state == "verifying" else "preparing"
        item["checks"] = []
        for job in db.scalars(select(StorageJob).order_by(StorageJob.created_at.desc()).limit(30)):
            if job.payload.get("root_id") == source["id"] and job.result.get("checks"):
                item["checks"] = job.result["checks"]
                break
        if config:
            try:
                location = ensure_location(db, config)
            except StorageError as error:
                item.update(
                    state="unavailable", message=str(error), access_count=0, access_accounts=[]
                )
                continue
            if location.retired:
                item.update(
                    state="unavailable",
                    message="This registration was disconnected. Register a new location.",
                    access_count=0,
                    access_accounts=[],
                )
                continue
            grants = db.scalars(
                select(StorageGrant).where(StorageGrant.location_id == location.id)
            ).all()
            item["access_count"] = len(grants)
            item["access_accounts"] = [
                {
                    "user_id": grant.principal_id,
                    "level": "read" if config.read_only else grant.level,
                }
                for grant in grants
            ]
    db.commit()
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
            "managed_area": snapshot.get("managed_area") or None,
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
                "current": user.id == principal.id,
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
    body.restore_grants = False
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
    if body.action in {"add", "init", "preflight"} and body.path:
        exact = next((root for root in roots if root["source"] == body.path), None)
        if exact:
            desired = (
                "managed"
                if body.managed or body.action == "init"
                else "shared"
                if body.shared
                else "assigned"
            )
            if exact["kind"] != desired:
                raise HTTPException(
                    409,
                    "This folder has a different registered purpose. Open its location details.",
                )
            body.root_id = exact["id"]
            current = exact
            if body.action != "preflight":
                if connected_now(exact, value, settings, principal.id):
                    job = StorageJob(
                        id=str(uuid4()),
                        principal_id=principal.id,
                        action="inspect",
                        payload={"root_id": exact["id"]},
                        state="completed",
                        message="This directory is already connected. Open its location details.",
                        result={"existing_root_id": exact["id"]},
                        created_at=now(),
                        updated_at=now(),
                    )
                    db.add(job)
                    db.commit()
                    return job_view(job)
                body = normalize_repair(body, current, value, db)
    if body.action == "repair":
        if current is None:
            raise HTTPException(404, "This location is no longer registered.")
        body = normalize_repair(body, current, value, db)
    body.automatic_access, body.grant_access = True, False
    if body.action in {"add", "init", "preflight"}:
        if not body.path.startswith("/") or not body.label.strip():
            raise HTTPException(422, "Choose an absolute host path and a location name.")
        if body.action == "init" and any(root["kind"] == "managed" for root in roots):
            raise HTTPException(
                409,
                "Private folders already have a base. "
                "Use Change base directory to copy and switch safely.",
            )
        if (
            not body.shared
            and body.action != "init"
            and not (body.action == "preflight" and body.managed)
        ):
            user = db.get(LocalUser, body.owner) if body.owner else None
            if user is None or not user.active:
                raise HTTPException(422, "Choose an active account.")
    if body.action == "repair":
        body.create_directory = False
    if body.create_directory and (not body.shared or body.action not in {"add", "preflight"}):
        raise HTTPException(422, "New shared directories use Connect shared folder.")
    if body.create_directory:
        body.selinux = "private"
    if body.shared and body.managed:
        raise HTTPException(422, "A location cannot be both private and shared.")
    if body.shared:
        body.owner = None
    if body.grants is not None:
        ids = [grant.user_id for grant in body.grants]
        if len(ids) != len(set(ids)):
            raise HTTPException(422, "Choose each account only once.")
        for grant in body.grants:
            user = db.get(LocalUser, grant.user_id)
            if user is None or not user.active:
                raise HTTPException(422, "Choose active accounts for this location.")
            if body.read_only and grant.level == "write":
                raise HTTPException(422, "A read-only host mount cannot grant write access.")
    if (
        body.shared
        and body.action in {"add", "preflight"}
        and not any(grant.level != "none" for grant in body.grants or [])
    ):
        raise HTTPException(422, "Choose at least one account with access.")
    if body.action in {"remove", "update", "refresh-identity", "check"} and current is None:
        raise HTTPException(404, "Unknown storage location.")
    if body.action == "update":
        if not body.label.strip():
            raise HTTPException(422, "Enter a location name.")
        if current["kind"] == "assigned" and body.owner != current.get("owner"):
            raise HTTPException(422, "Use Manage access to change account permissions.")
    if body.action == "relocate" and (
        current is None or current["kind"] != "managed" or not body.path.startswith("/")
    ):
        raise HTTPException(422, "Choose a new absolute path for the existing private-folder base.")
    if body.action not in {"browse", "preflight", "check"} and not body.confirmed:
        raise HTTPException(422, "Review and confirm the storage change first.")
    if body.action in {"add", "init", "remove", "update", "refresh-identity", "relocate", "repair"}:
        load_manifest(settings.storage_manifest)
    if body.action == "add":
        body.root_id = "folder-" + uuid4().hex[:12]
    if body.action == "init":
        body.root_id = "personal"
    previously_blocked = body.root_id in value.blocked_roots
    if body.action in {"add", "init", "remove", "update", "refresh-identity", "relocate", "repair"}:
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
    payload = {**job.payload, "automatic_access": True, "grant_access": False}
    roots = value.snapshot.get("roots", [])
    current = next((root for root in roots if root["id"] == payload.get("root_id")), None)
    action = job.action
    if action in {"add", "init", "repair"} and current:
        repaired = normalize_repair(
            Operation.model_validate(
                {key: val for key, val in payload.items() if key in Operation.model_fields}
            ),
            current,
            value,
            db,
        )
        payload.update(repaired.model_dump())
        action = "repair"
    replacement = StorageJob(
        id=str(uuid4()),
        principal_id=principal.id,
        action=action,
        payload={
            **payload,
            "resume_id": job.payload.get("resume_id", job.id),
            "previously_blocked": job.payload.get("root_id") in value.blocked_roots,
        },
        state="queued",
        message="Retry requested.",
        result={},
        created_at=now(),
        updated_at=now(),
    )
    if job.action in {"add", "init", "remove", "update", "refresh-identity", "relocate", "repair"}:
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
        "managed_area": body.managed_area,
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
            locations = {root.id: ensure_location(db, root) for root in manifest.roots}
            target = locations.get(job.payload.get("root_id"))
            if (
                target
                and (job.action in {"add", "init"} or job.payload.get("restore_grants"))
                and job.payload.get("grants") is not None
            ):
                for grant in db.scalars(
                    select(StorageGrant).where(StorageGrant.location_id == target.id)
                ):
                    db.delete(grant)
                db.flush()
                for grant in job.payload["grants"]:
                    if grant["level"] != "none":
                        db.add(
                            StorageGrant(
                                location_id=target.id,
                                principal_id=grant["user_id"],
                                level=grant["level"],
                                version=str(uuid4()),
                            )
                        )
                target.revision += 1
                db.flush()
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
                    if (
                        job.action in {"add", "update"}
                        and config.kind != "managed"
                        and config.read_only != job.payload.get("read_only", False)
                    ):
                        raise StorageError("The applied host access mode differs from the request.")
                    if (
                        job.action == "add"
                        and job.payload.get("shared")
                        and config.kind != "shared"
                    ):
                        raise StorageError("The requested shared directory was not applied.")
                    if job.action == "setup":
                        source = next(r for r in body.roots if r.id == config.id)
                        if (
                            config.kind != job.payload.get("kind", "managed")
                            or source.source != job.payload["path"]
                        ):
                            raise StorageError("The applied storage location differs from setup.")
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
                        checks = [
                            {
                                "code": "mount_identity",
                                "state": "passed",
                                "message": "Runtime mount identity verified",
                            }
                        ]
                        if not os.access(".", os.R_OK | os.X_OK, dir_fd=fd):
                            raise HTTPException(
                                503,
                                {
                                    "message": "Runtime read denied by host access policy.",
                                    "checks": [
                                        *checks,
                                        {
                                            "code": "runtime_read",
                                            "state": "blocked",
                                            "message": "Runtime directory read/traverse denied",
                                        },
                                    ],
                                },
                            )
                        checks.append(
                            {
                                "code": "runtime_read",
                                "state": "passed",
                                "message": "Runtime read and traverse verified",
                            }
                        )
                        if not config.read_only and os.fstatvfs(fd).f_flag & os.ST_RDONLY:
                            raise HTTPException(
                                503,
                                {
                                    "message": "The mounted filesystem is read-only.",
                                    "checks": [
                                        *checks,
                                        {
                                            "code": "filesystem_writable",
                                            "state": "blocked",
                                            "message": "Filesystem is read-only",
                                        },
                                    ],
                                },
                            )
                        if not config.read_only and not os.access(
                            ".", os.W_OK | os.X_OK, dir_fd=fd
                        ):
                            raise HTTPException(
                                503,
                                {
                                    "message": "Runtime write denied by host access policy.",
                                    "checks": [
                                        *checks,
                                        {
                                            "code": "runtime_write",
                                            "state": "blocked",
                                            "message": "Runtime directory write denied",
                                        },
                                    ],
                                },
                            )
                        job.result = {
                            **body.result,
                            "checks": [*body.result.get("checks", []), *checks],
                        }
                    if config.kind == "managed":
                        ids = db.scalars(
                            select(StorageGrant.principal_id).where(
                                StorageGrant.location_id == locations[config.id].id
                            )
                        ).all()
                        for user in db.scalars(
                            select(LocalUser).where(
                                LocalUser.active.is_(True), LocalUser.id.in_(ids)
                            )
                        ):
                            with service.root(config.id, user.id, provision=True):
                                pass
                    if not config.read_only:
                        with service.root(config.id, owner, write=True, base=True) as fd:
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
            retire_missing(db, manifest)
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
            job.result
            if body.state == "completed" and job.action not in {"browse", "preflight"}
            else body.result,
            now(),
        )
        if body.state == "completed" and job.action not in {"browse", "preflight"}:
            job.result = {
                **job.result,
                "checks": [
                    *[
                        check
                        for check in job.result.get("checks", [])
                        if check.get("code") != "runtime_access"
                    ],
                    {
                        "code": "runtime_access",
                        "state": "passed",
                        "message": "API read and requested write operations verified",
                    },
                ],
            }
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
    retire_missing(db, manifest)
    for job in db.scalars(select(StorageJob).where(StorageJob.state == "failed")):
        if job.action == "remove" and job.payload.get("root_id") in removed:
            job.result = {**job.result, "resolved": True}
    db.commit()
    return {"message": "Removed locations reconciled. Existing storage permissions are unchanged."}
