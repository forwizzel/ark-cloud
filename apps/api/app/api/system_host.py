import asyncio
import base64
import hmac
import json
from contextlib import suppress
from time import monotonic
from typing import Annotated
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.auth import _managed_https_request
from app.auth.service import SESSION_COOKIE, _as_utc, get_session, now, token_hash
from app.core.config import get_settings
from app.core.database import SessionLocal, get_db_session
from app.dependencies import require_admin, require_principal
from app.models import AuthSession, LocalUser, SystemControl, SystemJob
from app.schemas.system_host import (
    HostInformation,
    HostStatus,
    JobRequest,
    ProcessList,
    ServiceList,
    Snapshot,
)
from app.services.system_control import (
    IDLE_SECONDS,
    MAX_FRAME,
    RECONNECT_SECONDS,
    audit,
    broker,
    create_job,
    create_terminal,
    job_response,
    principal_valid,
    reconcile,
    status,
)

router = APIRouter(tags=["system host"])
DB = Annotated[Session, Depends(get_db_session)]
Admin = Annotated[object, Depends(require_admin)]
Reader = Annotated[object, Depends(require_principal)]


@router.get("/system/overview", response_model=HostInformation)
@router.get("/system/vitals", response_model=HostInformation)
def host_information(db: DB, _: Reader):
    snapshot = broker.snapshot
    value = (
        snapshot.model_dump(mode="json", exclude={"processes", "services", "capabilities"})
        if snapshot
        else None
    )
    connection = status(db)
    # Shell/account and enabled unit names are administrator metadata.
    policy = connection.pop("policy")
    connection["capabilities"] = {
        key: bool(policy and policy.get(key)) for key in ("terminal", "power", "processes")
    }
    return {**connection, "snapshot": value, "history": list(broker.history)}


@router.get("/admin/system/status", response_model=HostStatus)
def admin_status(db: DB, _: Admin):
    return status(db)


@router.get("/admin/system/services", response_model=ServiceList)
def services(_: Admin):
    return {"items": broker.snapshot.services if broker.snapshot else []}


@router.get("/admin/system/processes", response_model=ProcessList)
def processes(_: Admin, offset: int = 0, limit: int = 100):
    items = broker.snapshot.processes if broker.snapshot else []
    offset, limit = max(0, offset), min(2048, max(1, limit))
    return {"items": items[offset : offset + limit], "total": len(items)}


@router.post("/admin/system/jobs")
async def submit_job(request: JobRequest, db: DB, principal: Admin):
    return create_job(db, principal, request)


@router.get("/admin/system/jobs/{job_id}")
def read_job(job_id: str, db: DB, _: Admin):
    reconcile(db)
    job = db.get(SystemJob, job_id)
    if not job:
        raise HTTPException(404, "Operation not found.")
    return job_response(job)


@router.post("/admin/system/revoke")
async def revoke(db: DB, principal: Admin):
    control = db.get(SystemControl, 1)
    if control:
        control.token_hash = None
    broker.disconnect()
    broker.snapshot = None
    broker.history.clear()
    audit(db, principal.id, "agent_revoke")
    db.commit()
    return {"state": "revoked"}


@router.post("/admin/system/terminal/sessions")
async def start_terminal(db: DB, principal: Admin):
    return create_terminal(db, principal)


@router.post("/admin/system/terminal/sessions/{session_id}/attach")
async def resume_terminal(session_id: str, db: DB, principal: Admin):
    return create_terminal(db, principal, session_id)


@router.post("/admin/system/terminal/sessions/{session_id}/end")
async def end_terminal(session_id: str, db: DB, principal: Admin):
    terminal = broker.terminals.get(session_id)
    if terminal and terminal.auth_id == principal.session_id:
        broker.finish(terminal)
        audit(db, principal.id, "terminal_end", session_id)
        db.commit()
    return {"state": "ended"}


def origin_allowed(ws, db):
    try:
        origin = urlsplit(ws.headers.get("origin", ""))
        if origin.username or origin.password or origin.path or origin.query or origin.fragment:
            return False
        if _managed_https_request(ws, db):
            return (
                origin.scheme == "https"
                and origin.hostname == ws.headers.get("x-forwarded-host")
                and origin.port in {None, 443}
            )
        return origin.scheme in {"http", "https"} and origin.netloc == ws.headers.get("host")
    except ValueError:
        return False


@router.websocket("/system/terminal/{session_id}")
async def terminal_socket(ws: WebSocket, session_id: str):
    terminal = broker.terminals.get(session_id)
    with SessionLocal() as db:
        session = get_session(db, get_settings(), ws.cookies.get(SESSION_COOKIE))
        allowed = (
            terminal
            and session
            and session.id == terminal.auth_id
            and principal_valid(db, terminal)
        )
        origin_valid = origin_allowed(ws, db)
    if not allowed or not origin_valid or terminal.ended or terminal.attached:
        await ws.close(code=1008)
        return
    await ws.accept()
    tasks = []
    owns_attachment = False
    try:
        raw_hello = await asyncio.wait_for(ws.receive_text(), timeout=5)
        if len(raw_hello) > 4096:
            raise ValueError("Attachment handshake too large")
        hello = json.loads(raw_hello)
        if (
            monotonic() > terminal.grant_until
            or not terminal.grant
            or terminal.attached
            or terminal.ended
            or not hmac.compare_digest(str(hello.get("grant", "")), terminal.grant)
        ):
            await ws.close(code=1008)
            return
        terminal.grant = ""
        terminal.attached = True
        owns_attachment = True
        terminal.touched = monotonic()
        while not terminal.queue.empty():
            terminal.queue.get_nowait()
        if terminal.replay:
            await ws.send_json(
                {"type": "notice", "message": "Reattached. Recent output follows (bounded replay)."}
            )
            for frame in terminal.replay:
                await ws.send_json(frame)

        async def output():
            while True:
                frame = await terminal.queue.get()
                await asyncio.wait_for(ws.send_json(frame), timeout=10)
                if frame["type"] == "ended":
                    await ws.close()
                    return

        async def input_frames():
            while True:
                raw = await ws.receive_text()
                if len(raw) > MAX_FRAME:
                    raise ValueError("Frame too large")
                frame = json.loads(raw)
                if terminal.ended:
                    return
                if frame.get("type") == "input":
                    data = frame.get("data", "")
                    base64.b64decode(data, validate=True)
                    broker.send({"type": "terminal_input", "id": session_id, "data": data})
                    terminal.touched = monotonic()
                elif frame.get("type") == "resize":
                    cols, rows = int(frame["cols"]), int(frame["rows"])
                    if not 2 <= cols <= 500 or not 2 <= rows <= 200:
                        raise ValueError("Invalid size")
                    broker.send(
                        {"type": "terminal_resize", "id": session_id, "cols": cols, "rows": rows}
                    )
                else:
                    raise ValueError("Invalid terminal message")

        tasks = [asyncio.create_task(output()), asyncio.create_task(input_frames())]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect, TimeoutError, ValueError, KeyError, TypeError, HTTPException:
        pass
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if owns_attachment:
            terminal.attached = False
            terminal.detached = monotonic()
        with suppress(RuntimeError):
            await ws.close()


@router.websocket("/system-agent/connect")
async def agent_socket(ws: WebSocket):
    token = ws.headers.get("authorization", "").removeprefix("Bearer ")
    credential = token_hash(token)
    with SessionLocal() as db:
        control = db.get(SystemControl, 1)
        allowed = (
            control and control.token_hash and hmac.compare_digest(control.token_hash, credential)
        )
    if not allowed or broker.connected:
        await ws.close(code=1008)
        return
    connection_id = str(uuid4())
    # Reserve ownership before the first await; old handlers cannot mutate a new connection.
    broker.connected, broker.connection_id = True, connection_id
    broker.seen = 0
    try:
        await ws.accept()
    except BaseException:
        broker.disconnect()
        raise
    if broker.connection_id != connection_id:
        await ws.close(code=1008)
        return
    if broker.credential != credential:
        broker.snapshot = None
        broker.history.clear()
    broker.commands = asyncio.Queue(maxsize=128)
    broker.connected, broker.credential, broker.seen = True, credential, monotonic()
    tasks = []
    try:

        async def commands():
            while True:
                frame = await broker.commands.get()
                if broker.connection_id != connection_id:
                    return
                if frame["type"] == "job":
                    with SessionLocal() as db:
                        job = db.get(SystemJob, frame["id"])
                        reconcile(db)
                        if not job or job.state != "accepted":
                            continue
                        session = db.get(AuthSession, job.auth_id)
                        user = db.get(LocalUser, job.principal_id)
                        control = db.get(SystemControl, 1)
                        if (
                            not session
                            or _as_utc(session.expires_at) <= now()
                            or not user
                            or not user.active
                            or user.role != "admin"
                            or not control
                            or control.token_hash != credential
                        ):
                            job.state, job.message = (
                                "failed",
                                "Authorization changed before dispatch.",
                            )
                            job.updated_at = now()
                            db.commit()
                            continue
                        job.state, job.updated_at = "dispatched", now()
                        db.commit()
                await asyncio.wait_for(ws.send_json(frame), timeout=10)

        async def reports():
            while True:
                raw = await ws.receive_text()
                if broker.connection_id != connection_id:
                    return
                if len(raw) > 2_000_000:
                    raise ValueError("Report too large")
                frame = json.loads(raw)
                broker.seen = monotonic()
                if frame.get("type") == "snapshot":
                    snapshot = Snapshot.model_validate(frame["snapshot"])
                    broker.snapshot = snapshot
                    broker.history.append(
                        {
                            "collected_at": snapshot.collected_at.isoformat(),
                            "cpu": snapshot.compute.percent,
                            "memory": snapshot.memory.usage.percent
                            if snapshot.memory.usage
                            else None,
                        }
                    )
                    with SessionLocal() as db:
                        control = db.get(SystemControl, 1)
                        control.last_seen_at = now()
                        reconcile(db)
                        db.commit()
                elif frame.get("type") == "job_result":
                    with SessionLocal() as db:
                        job = db.get(SystemJob, frame["id"])
                        if job and job.state in {"dispatched", "unknown"}:
                            state = frame.get("state")
                            if state not in {"succeeded", "failed", "unknown", "expired"}:
                                raise ValueError("Invalid result")
                            job.state, job.message = state, str(frame.get("message", ""))[:500]
                            job.updated_at = now()
                            db.commit()
                elif frame.get("type") in {"terminal_output", "terminal_exit"}:
                    terminal = broker.terminals.get(frame.get("id"))
                    if terminal and not terminal.ended:
                        if frame["type"] == "terminal_exit":
                            broker.finish(terminal, notify=False)
                            with SessionLocal() as db:
                                audit(db, terminal.principal_id, "terminal_end", terminal.id)
                                db.commit()
                        else:
                            data = frame["data"]
                            if len(data) > MAX_FRAME:
                                raise ValueError("Terminal output too large")
                            base64.b64decode(data, validate=True)
                            output = {"type": "output", "data": data}
                            terminal.replay.append(output)
                            if terminal.attached:
                                try:
                                    terminal.queue.put_nowait(output)
                                except asyncio.QueueFull:
                                    broker.finish(terminal)
                else:
                    raise ValueError("Invalid report")

        async def guard():
            while True:
                await asyncio.sleep(2)
                with SessionLocal() as db:
                    control = db.get(SystemControl, 1)
                    if (
                        broker.connection_id != connection_id
                        or not broker.live()
                        or not control
                        or control.token_hash != credential
                    ):
                        return
                    for terminal in list(broker.terminals.values()):
                        if terminal.ended:
                            broker.terminals.pop(terminal.id, None)
                            continue
                        if (
                            not principal_valid(db, terminal)
                            or monotonic() - terminal.touched > IDLE_SECONDS
                            or (
                                not terminal.attached
                                and monotonic() - terminal.detached > RECONNECT_SECONDS
                            )
                        ):
                            broker.finish(terminal)
                            audit(db, terminal.principal_id, "terminal_end", terminal.id)
                    db.commit()

        tasks = [
            asyncio.create_task(commands()),
            asyncio.create_task(reports()),
            asyncio.create_task(guard()),
        ]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect, ValueError, ValidationError:
        pass
    finally:
        if broker.connection_id == connection_id:
            with SessionLocal() as db:
                for terminal in broker.terminals.values():
                    if not terminal.ended:
                        audit(db, terminal.principal_id, "terminal_disconnect", terminal.id)
                db.commit()
            broker.disconnect()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with suppress(RuntimeError):
            await ws.close()
