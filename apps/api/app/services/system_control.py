"""Single-worker host broker. Streams are bounded and never persisted."""

import asyncio
import secrets
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.service import _as_utc, now
from app.models import AuthSession, LocalUser, SystemAudit, SystemControl, SystemJob
from app.schemas.system_host import JobRequest, Policy, Snapshot

SAMPLE_SECONDS = 5
STALE_SECONDS = 15
JOB_SECONDS = 30
IDLE_SECONDS = 900
RECONNECT_SECONDS = 30
GRANT_SECONDS = 20
MAX_FRAME = 32768


def audit(db: Session, principal: str, event: str, target: str = "") -> None:
    db.add(
        SystemAudit(
            id=str(uuid4()),
            principal_id=principal,
            event=event,
            target=target[:128],
            created_at=now(),
        )
    )
    db.execute(delete(SystemAudit).where(SystemAudit.created_at < now() - timedelta(days=30)))


@dataclass
class TerminalSession:
    id: str
    principal_id: str
    auth_id: str
    grant: str
    grant_until: float
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=64))
    replay: deque = field(default_factory=lambda: deque(maxlen=64))
    touched: float = field(default_factory=monotonic)
    detached: float = field(default_factory=monotonic)
    attached: bool = False
    ended: bool = False


class HostBroker:
    def __init__(self):
        self.commands = asyncio.Queue(maxsize=128)
        self.connected = False
        self.seen = 0.0
        self.snapshot: Snapshot | None = None
        self.history = deque(maxlen=120)
        self.terminals: dict[str, TerminalSession] = {}
        self.credential: str | None = None
        self.connection_id: str | None = None

    def live(self):
        return self.connected and monotonic() - self.seen < STALE_SECONDS

    def send(self, message):
        if not self.live():
            raise HTTPException(409, "The host agent is offline. Reconnect it before continuing.")
        try:
            self.commands.put_nowait(message)
        except asyncio.QueueFull as error:
            raise HTTPException(503, "Host operations are busy. Try again shortly.") from error

    def finish(self, terminal, notify=True):
        if terminal.ended:
            return
        terminal.ended = True
        if notify and self.live():
            try:
                self.send({"type": "terminal_end", "id": terminal.id})
            except HTTPException:
                # A full queue must fail closed: disconnecting kills all host PTYs.
                self.connected = False
        while not terminal.queue.empty():
            terminal.queue.get_nowait()
        terminal.queue.put_nowait({"type": "ended"})

    def disconnect(self):
        self.connected = False
        self.connection_id = None
        for terminal in self.terminals.values():
            self.finish(terminal, notify=False)


broker = HostBroker()


def status(db: Session):
    control = db.get(SystemControl, 1)
    state = (
        "not_enrolled"
        if not control
        else "revoked"
        if not control.token_hash
        else (
            "connected" if broker.live() and broker.credential == control.token_hash else "offline"
        )
    )
    return {
        "state": state,
        "scope": "host",
        "collected_at": (broker.snapshot.collected_at if broker.snapshot else None),
        "policy": effective_policy(control).model_dump()
        if control and control.token_hash
        else None,
    }


def principal_valid(db: Session, terminal: TerminalSession):
    session = db.get(AuthSession, terminal.auth_id)
    user = db.get(LocalUser, terminal.principal_id)
    return bool(
        session
        and _as_utc(session.expires_at) > now()
        and user
        and user.active
        and user.password_hash
        and user.role == "admin"
    )


def effective_policy(control):
    owner = Policy.model_validate(control.policy)
    if not broker.snapshot:
        return owner.model_copy(update={"terminal": False, "power": False, "services": []})
    effective = broker.snapshot.capabilities
    return owner.model_copy(
        update={
            "terminal": owner.terminal and effective.terminal,
            "power": owner.power and effective.power,
            "processes": owner.processes and effective.processes,
            "services": [
                s.model_copy(
                    update={
                        "actions": [
                            a
                            for a in s.actions
                            if any(
                                e.unit == s.unit and e.scope == s.scope and a in e.actions
                                for e in effective.services
                            )
                        ]
                    }
                )
                for s in owner.services
            ],
        }
    )


def job_response(job):
    return {
        "id": job.id,
        "state": job.state,
        "message": job.message,
        "payload": job.payload,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def reconcile(db: Session):
    for job in db.scalars(
        select(SystemJob).where(SystemJob.state.in_(["accepted", "dispatched", "unknown"]))
    ):
        previous = job.state
        if (
            job.payload["action"] == "restart"
            and job.state in {"dispatched", "unknown"}
            and broker.live()
            and broker.snapshot
            and (job.boot_id != broker.snapshot.boot_id)
        ):
            job.state, job.message = "succeeded", "Host reconnected after restarting."
        elif _as_utc(job.deadline) <= now() and job.state == "accepted":
            job.state, job.message = "expired", "The operation expired before dispatch."
        elif _as_utc(job.deadline) <= now() and job.state == "dispatched":
            job.state, job.message = (
                "unknown",
                "Host connection interrupted; outcome is not verified.",
            )
        if previous != job.state:
            job.updated_at = now()
    db.execute(delete(SystemJob).where(SystemJob.updated_at < now() - timedelta(days=30)))
    db.commit()


def create_job(db: Session, principal, request: JobRequest):
    previous = db.scalar(
        select(SystemJob).where(SystemJob.idempotency_key == request.idempotency_key)
    )
    payload = request.payload.model_dump()
    if previous:
        if previous.principal_id != principal.id or previous.payload != payload:
            raise HTTPException(409, "This operation key was already used.")
        return job_response(previous)
    control = db.get(SystemControl, 1)
    if (
        not control
        or not control.token_hash
        or not broker.live()
        or not broker.snapshot
        or broker.credential != control.token_hash
    ):
        raise HTTPException(409, "A connected, enrolled host is required.")
    policy = effective_policy(control)
    action = payload["action"]
    permitted = policy.power if action in {"restart", "shutdown"} else policy.processes
    if action == "service":
        permitted = any(
            s.unit == payload["unit"]
            and s.scope == payload["scope"]
            and payload["operation"] in s.actions
            for s in policy.services
        )
    if not permitted:
        raise HTTPException(403, "This action is not enabled by the host owner.")
    reconcile(db)
    for active in db.scalars(
        select(SystemJob).where(SystemJob.state.in_(["accepted", "dispatched"]))
    ):
        if (
            action in {"restart", "shutdown"}
            or active.payload == payload
            or (action == "service" and active.payload.get("unit") == payload["unit"])
        ):
            raise HTTPException(409, "An operation for this target is already pending.")
    job = SystemJob(
        id=str(uuid4()),
        principal_id=principal.id,
        auth_id=principal.session_id,
        idempotency_key=request.idempotency_key,
        payload=payload,
        state="accepted",
        message="Operation accepted.",
        boot_id=broker.snapshot.boot_id,
        created_at=now(),
        updated_at=now(),
        deadline=now() + timedelta(seconds=JOB_SECONDS),
    )
    db.add(job)
    audit(db, principal.id, action, payload.get("unit", str(payload.get("pid", "host"))))
    db.commit()
    broker.send(
        {
            "type": "job",
            "id": job.id,
            "payload": payload,
            "deadline": job.deadline.isoformat(),
            "boot_id": job.boot_id,
        }
    )
    return job_response(job)


def create_terminal(db, principal, session_id=None):
    control = db.get(SystemControl, 1)
    if (
        not control
        or not control.token_hash
        or broker.credential != control.token_hash
        or not effective_policy(control).terminal
    ):
        raise HTTPException(403, "Terminal access is not enabled by the host owner.")
    if session_id:
        if not broker.live():
            raise HTTPException(409, "The host agent is offline.")
        terminal = broker.terminals.get(session_id)
        if not terminal or terminal.ended or terminal.auth_id != principal.session_id:
            raise HTTPException(404, "This terminal session has ended.")
        if terminal.attached:
            raise HTTPException(409, "This terminal is already attached.")
        terminal.grant = secrets.token_urlsafe(32)
        terminal.grant_until = monotonic() + GRANT_SECONDS
    else:
        active = [t for t in broker.terminals.values() if not t.ended]
        if len(active) >= 8 or any(t.auth_id == principal.session_id for t in active):
            raise HTTPException(409, "End the existing terminal before starting another.")
        terminal = TerminalSession(
            str(uuid4()),
            principal.id,
            principal.session_id,
            secrets.token_urlsafe(32),
            monotonic() + GRANT_SECONDS,
        )
        broker.send({"type": "terminal_start", "id": terminal.id})
        broker.terminals[terminal.id] = terminal
        audit(db, principal.id, "terminal_connect", terminal.id)
        db.commit()
    return {"id": terminal.id, "grant": terminal.grant, "reconnect_seconds": RECONNECT_SECONDS}
