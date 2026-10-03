import asyncio
import base64
from datetime import timedelta
from time import monotonic

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.system_host import origin_allowed
from app.auth.service import now, token_hash
from app.core.database import SessionLocal
from app.main import app
from app.models import LocalUser, SystemControl, SystemJob, TailscaleControl
from app.schemas.system_host import Snapshot
from app.services.system_control import broker, reconcile


def snapshot():
    return {
        "boot_id": "boot-one",
        "collected_at": now().isoformat(),
        "identity": {
            "hostname": "test-host",
            "os": "Test Linux",
            "kernel": "6-test",
            "architecture": "x86_64",
            "boot_time": now().isoformat(),
            "uptime_seconds": 1,
        },
        "compute": {},
        "memory": {},
        "capabilities": {
            "terminal": True,
            "power": True,
            "processes": True,
            "shell": "/bin/bash",
            "account": "host-owner",
            "services": [],
        },
        "processes": [
            {
                "pid": 123,
                "started_at": 1,
                "owner": "secret-owner",
                "name": "private-tool",
                "memory_bytes": 100,
                "state": "sleeping",
            }
        ],
    }


@pytest.fixture(autouse=True)
def clean_broker():
    broker.disconnect()
    broker.terminals.clear()
    broker.snapshot = None
    broker.history.clear()
    broker.commands = asyncio.Queue(maxsize=128)
    yield
    broker.disconnect()
    broker.terminals.clear()


def enroll():
    with SessionLocal() as db:
        db.add(
            SystemControl(
                id=1, token_hash=token_hash("agent-secret"), policy=snapshot()["capabilities"]
            )
        )
        db.commit()


def login(client):
    response = client.post("/auth/login", json={"username": "ark", "password": "test-password"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def online():
    broker.connected = True
    broker.seen = monotonic()
    broker.credential = token_hash("agent-secret")
    broker.snapshot = Snapshot.model_validate(snapshot())


def test_read_only_host_payload_excludes_sensitive_metadata():
    enroll()
    online()
    with TestClient(app) as client:
        login(client)
        with SessionLocal() as db:
            db.get(LocalUser, "ark").role = "member"
            db.commit()
        response = client.get("/system/overview")
        assert response.status_code == 200
        assert response.json()["state"] == "connected"
        assert "processes" not in response.json()["snapshot"]
        assert "capabilities" not in response.json()["snapshot"]
        assert "host-owner" not in response.text
        assert client.get("/admin/system/processes").status_code == 403
        assert client.post("/admin/system/terminal/sessions", json={}).status_code == 403


def test_job_csrf_idempotency_owner_policy_and_expiry():
    enroll()
    online()
    with TestClient(app) as client:
        headers = login(client)
        body = {"idempotency_key": "unique-operation-key", "payload": {"action": "restart"}}
        assert client.post("/admin/system/jobs", json=body).status_code == 403
        first = client.post("/admin/system/jobs", headers=headers, json=body)
        assert first.status_code == 200
        second = client.post("/admin/system/jobs", headers=headers, json=body)
        assert first.json()["id"] == second.json()["id"]
        assert broker.commands.qsize() == 1
        denied = {
            "idempotency_key": "other-operation-key",
            "payload": {
                "action": "service",
                "scope": "system",
                "unit": "not-enrolled.service",
                "operation": "stop",
            },
        }
        assert client.post("/admin/system/jobs", headers=headers, json=denied).status_code == 403
        with SessionLocal() as db:
            job = db.get(SystemJob, first.json()["id"])
            job.deadline = now() - timedelta(seconds=1)
            db.commit()
            reconcile(db)
            assert job.state == "expired"


def test_snapshot_protocol_and_terminal_roundtrip_with_single_use_grant():
    enroll()
    with TestClient(app) as client:
        headers = login(client)
        with client.websocket_connect(
            "/system-agent/connect", headers={"Authorization": "Bearer agent-secret"}
        ) as agent:
            agent.send_json({"type": "snapshot", "snapshot": snapshot()})
            # Wait for processing without sleeping or polling an unbounded loop.
            for _ in range(100):
                if client.get("/system/overview").json()["snapshot"]:
                    break
            created = client.post("/admin/system/terminal/sessions", headers=headers, json={})
            assert created.status_code == 200
            grant = created.json()
            assert agent.receive_json()["type"] == "terminal_start"
            with client.websocket_connect(
                f"/system/terminal/{grant['id']}", headers={"Origin": "http://testserver"}
            ) as terminal:
                terminal.send_json({"grant": grant["grant"]})
                terminal.send_json({"type": "input", "data": base64.b64encode(b"pwd\n").decode()})
                assert base64.b64decode(agent.receive_json()["data"]) == b"pwd\n"
                agent.send_json(
                    {
                        "type": "terminal_output",
                        "id": grant["id"],
                        "data": base64.b64encode(b"/home/owner\r\n").decode(),
                    }
                )
                assert base64.b64decode(terminal.receive_json()["data"]) == b"/home/owner\r\n"
                assert (
                    client.post(
                        f"/admin/system/terminal/sessions/{grant['id']}/attach",
                        headers=headers,
                        json={},
                    ).status_code
                    == 409
                )
                client.post(
                    f"/admin/system/terminal/sessions/{grant['id']}/end", headers=headers, json={}
                )
                assert terminal.receive_json()["type"] == "ended"
            assert agent.receive_json()["type"] == "terminal_end"


def test_origin_rejection_and_revocation_close_session():
    enroll()
    online()
    with TestClient(app) as client:
        headers = login(client)
        grant = client.post("/admin/system/terminal/sessions", headers=headers, json={}).json()
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                f"/system/terminal/{grant['id']}", headers={"Origin": "https://foreign.example"}
            ),
        ):
            pass
        response = client.post("/admin/system/revoke", headers=headers, json={})
        assert response.status_code == 200
        assert broker.terminals[grant["id"]].ended
        assert client.get("/system/overview").json()["snapshot"] is None


def test_expired_attachment_grant_is_rejected_without_extending_session_lifetime():
    enroll()
    online()
    with TestClient(app) as client:
        headers = login(client)
        grant = client.post("/admin/system/terminal/sessions", headers=headers, json={}).json()
        terminal = broker.terminals[grant["id"]]
        terminal.grant_until = monotonic() - 1
        detached = terminal.detached
        with client.websocket_connect(
            f"/system/terminal/{grant['id']}", headers={"Origin": "http://testserver"}
        ) as socket:
            socket.send_json({"grant": grant["grant"]})
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
        assert terminal.detached == detached
        assert not terminal.attached
        replacement = client.post(
            f"/admin/system/terminal/sessions/{grant['id']}/attach", headers=headers, json={}
        )
        assert replacement.status_code == 200
        assert replacement.json()["grant"] != grant["grant"]


def test_snapshot_rejects_nonfinite_and_oversized_measurements():
    from pydantic import ValidationError

    data = snapshot()
    data["compute"]["percent"] = float("nan")
    with pytest.raises(ValidationError):
        Snapshot.model_validate(data)
    data["compute"]["percent"] = 101
    with pytest.raises(ValidationError):
        Snapshot.model_validate(data)


def test_remote_origin_requires_authenticated_gateway_proof():
    from types import SimpleNamespace

    with SessionLocal() as db:
        control = db.get(TailscaleControl, 1)
        if not control:
            control = TailscaleControl(id=1)
            db.add(control)
        control.token_hash = token_hash("gateway-proof")
        db.commit()
        headers = {
            "origin": "https://ark.example.ts.net",
            "host": "localhost:5173",
            "x-forwarded-host": "ark.example.ts.net",
        }
        assert not origin_allowed(SimpleNamespace(headers=headers), db)
        headers["X-Ark-Remote-Access"] = "gateway-proof"
        assert origin_allowed(SimpleNamespace(headers=headers), db)
        headers["origin"] = "https://foreign.example"
        assert not origin_allowed(SimpleNamespace(headers=headers), db)
