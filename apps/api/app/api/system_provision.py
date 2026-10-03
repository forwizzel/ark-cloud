"""UI System setup executed by the deployment-owned, already-enrolled host manager."""

from datetime import timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.storage_admin import host_manager
from app.auth.service import Principal, _as_utc, now
from app.core.database import get_db_session
from app.dependencies import require_admin
from app.models import (
    AuthSession,
    LocalUser,
    StorageControl,
    SystemControl,
    SystemProvisionControl,
    SystemProvisionJob,
)
from app.schemas.system_provision import Configuration, Inventory, Operation, Report
from app.services.system_control import audit, broker, status

router = APIRouter(tags=["system administration"])
DB = Annotated[Session, Depends(get_db_session)]
Admin = Annotated[Principal, Depends(require_admin)]
Manager = Annotated[object, Depends(host_manager)]
ACTIVE = ("queued", "applying", "verifying")


def control(db):
    value = db.get(SystemProvisionControl, 1)
    if value is None:
        value = SystemProvisionControl(id=1, inventory={}, configuration={})
        db.add(value)
        db.flush()
    return value


def online(db, value):
    manager = db.get(StorageControl, 1)
    return bool(
        manager
        and manager.token_hash
        and value.last_seen_at
        and now() - _as_utc(value.last_seen_at) < timedelta(seconds=30)
    )


def view(job):
    return {
        "id": job.id,
        "state": job.state,
        "message": job.message,
        "payload": job.payload,
        "created_at": _as_utc(job.created_at),
        "updated_at": _as_utc(job.updated_at),
    }


def authorized(db, job):
    user = db.get(LocalUser, job.principal_id)
    session = db.get(AuthSession, job.auth_id)
    return bool(
        user
        and user.active
        and user.password_hash
        and user.role == "admin"
        and session
        and _as_utc(session.expires_at) > now()
    )


def prune(db):
    for job in db.scalars(select(SystemProvisionJob).where(SystemProvisionJob.state.in_(ACTIVE))):
        if job.state == "queued" and (
            now() - _as_utc(job.created_at) > timedelta(minutes=10) or not authorized(db, job)
        ):
            job.state, job.message = "failed", "Request expired or administrator access changed."
            job.updated_at = now()
    db.flush()
    db.execute(
        delete(SystemProvisionJob)
        .where(SystemProvisionJob.updated_at < now() - timedelta(days=30))
        .execution_options(synchronize_session=False)
    )


@router.get("/admin/system/configuration")
def configuration(db: DB, _: Admin):
    value = control(db)
    prune(db)
    system = db.get(SystemControl, 1)
    saved = value.configuration or (
        {k: v for k, v in system.policy.items() if k != "account"} if system else {}
    )
    jobs = list(
        db.scalars(
            select(SystemProvisionJob).order_by(SystemProvisionJob.created_at.desc()).limit(20)
        )
    )
    db.commit()
    return {
        "host": status(db),
        "manager": {"online": online(db, value), "inventory": value.inventory or None},
        "configuration": Configuration.model_validate(saved).model_dump(),
        "jobs": [view(job) for job in jobs],
    }


def approved(configuration, inventory):
    if not inventory.supported:
        raise HTTPException(409, inventory.message or "Host management is unavailable.")
    if configuration.shell and configuration.shell not in inventory.shells:
        raise HTTPException(422, "Choose one of the host's installed shells.")
    if configuration.power and not inventory.power:
        raise HTTPException(422, "Power controls are not authorized on this host.")
    identities = set()
    for service in configuration.services:
        identity = (service.unit, service.scope)
        if (
            identity in identities
            or len(set(service.actions)) != len(service.actions)
            or not service.actions
            or not any(
                service.unit == item.unit
                and service.scope == item.scope
                and set(service.actions) <= set(item.actions)
                for item in inventory.services
            )
        ):
            raise HTTPException(422, "Choose permitted actions for an available host service.")
        identities.add(identity)


@router.post("/admin/system/configuration")
async def change_configuration(operation: Operation, db: DB, principal: Admin):
    previous = db.scalar(
        select(SystemProvisionJob).where(
            SystemProvisionJob.idempotency_key == operation.idempotency_key
        )
    )
    payload = operation.model_dump(exclude={"idempotency_key"})
    if previous:
        if previous.principal_id != principal.id or previous.payload != payload:
            raise HTTPException(409, "This request key was already used.")
        return view(previous)
    value = control(db)
    if operation.action == "connect" and not online(db, value):
        raise HTTPException(
            409, "Host management is temporarily offline. Retry when it reconnects."
        )
    prune(db)
    if db.scalar(select(SystemProvisionJob).where(SystemProvisionJob.state.in_(ACTIVE))):
        raise HTTPException(409, "System configuration is already being applied.")
    if operation.action == "connect":
        if operation.configuration is None:
            raise HTTPException(422, "System configuration is required.")
        approved(operation.configuration, Inventory.model_validate(value.inventory))
        value.configuration = operation.configuration.model_dump()
    job = SystemProvisionJob(
        id=str(uuid4()),
        principal_id=principal.id,
        auth_id=principal.session_id,
        idempotency_key=operation.idempotency_key,
        payload=payload,
        state="queued",
        message="Preparing System connection."
        if operation.action == "connect"
        else "Disconnecting System.",
        created_at=now(),
        updated_at=now(),
    )
    db.add(job)
    if operation.action == "disconnect":
        system = db.get(SystemControl, 1)
        if system:
            system.token_hash = None
        broker.disconnect()
        broker.snapshot = None
        broker.history.clear()
    audit(db, principal.id, "system_" + operation.action, job.id)
    db.commit()
    return view(job)


@router.get("/system-manager/work")
def work(db: DB, _: Manager):
    prune(db)
    job = db.scalar(
        select(SystemProvisionJob)
        .where(SystemProvisionJob.state.in_(ACTIVE))
        .order_by(SystemProvisionJob.created_at)
    )
    db.commit()
    return {"job": view(job) if job else None}


@router.post("/system-manager/report")
def report(body: Report, db: DB, _: Manager):
    value = control(db)
    value.inventory, value.last_seen_at = body.inventory.model_dump(), now()
    if body.job_id:
        job = db.get(SystemProvisionJob, body.job_id)
        if job is None:
            raise HTTPException(404, "System configuration operation not found.")
        if job.state not in ACTIVE:
            db.commit()
            return {"accepted": False, "message": "Result already recorded."}
        if job.state == "queued":
            if (
                body.state != "applying"
                or not authorized(db, job)
                or now() - _as_utc(job.created_at) > timedelta(minutes=10)
            ):
                job.state, job.message, job.updated_at = (
                    "failed",
                    "System request is no longer authorized.",
                    now(),
                )
                db.commit()
                return {"accepted": False}
            if job.payload["action"] == "connect":
                try:
                    approved(
                        Configuration.model_validate(job.payload["configuration"]), body.inventory
                    )
                except HTTPException as error:
                    job.state, job.message, job.updated_at = "failed", str(error.detail), now()
                    db.commit()
                    return {"accepted": False}
        if body.state == "completed" and job.payload["action"] == "connect":
            system = db.get(SystemControl, 1)
            requested = Configuration.model_validate(job.payload["configuration"])
            if (
                not system
                or not system.token_hash
                or not broker.live()
                or broker.credential != system.token_hash
                or not broker.snapshot
                or system.policy.get("account") != body.inventory.account
                or any(
                    system.policy.get(key) != getattr(requested, key)
                    for key in ("terminal", "power", "processes")
                )
                or (requested.shell and system.policy.get("shell") != requested.shell)
                or system.policy.get("services")
                != [item.model_dump() for item in requested.services]
            ):
                raise HTTPException(
                    409, "Waiting for the configured host agent to connect and report readings."
                )
        if body.state is None:
            raise HTTPException(422, "Operation state is required.")
        job.state, job.message, job.updated_at = body.state, body.message, now()
    db.commit()
    return {"accepted": True}
