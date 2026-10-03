from datetime import timedelta
from time import monotonic

import pytest
from fastapi.testclient import TestClient

from app.auth.service import now, token_hash
from app.core.database import SessionLocal
from app.main import app
from app.models import (
    LocalUser,
    StorageControl,
    SystemControl,
    SystemProvisionControl,
    SystemProvisionJob,
)
from app.schemas.system_host import Snapshot
from app.services.system_control import broker

INVENTORY = {
    "supported": True,
    "account": "owner",
    "default_shell": "/bin/bash",
    "shells": ["/bin/bash", "/bin/zsh"],
    "power": False,
    "services": [
        {"unit": "backup.service", "scope": "user", "actions": ["start", "stop", "restart"]}
    ],
    "message": "",
}
CONFIGURATION = {
    "terminal": True,
    "processes": True,
    "power": False,
    "shell": "/bin/zsh",
    "services": [],
}
MANAGER = {"Authorization": "Bearer fixture-manager"}


@pytest.fixture(autouse=True)
def setup_manager():
    broker.disconnect()
    broker.snapshot = None
    broker.history.clear()
    with SessionLocal() as db:
        db.add(StorageControl(id=1, token_hash=token_hash("fixture-manager"), snapshot={}))
        db.add(
            SystemProvisionControl(id=1, inventory=INVENTORY, configuration={}, last_seen_at=now())
        )
        db.commit()
    yield
    broker.disconnect()
    broker.snapshot = None


def login(client):
    value = client.post("/auth/login", json={"username": "ark", "password": "test-password"}).json()
    return {"X-CSRF-Token": value["csrf_token"]}


def request(key="fixture-system-key", configuration=None, action="connect"):
    return {
        "action": action,
        "configuration": configuration or CONFIGURATION,
        "idempotency_key": key,
    }


def test_configuration_is_admin_only_and_never_exposes_credentials():
    with TestClient(app) as client:
        assert client.get("/admin/system/configuration").status_code == 401
        headers = login(client)
        response = client.get("/admin/system/configuration", headers=headers)
        assert response.status_code == 200
        assert response.json()["manager"]["online"] is True
        assert response.json()["host"]["state"] == "not_enrolled"
        assert "fixture-manager" not in response.text
        with SessionLocal() as db:
            db.get(LocalUser, "ark").role = "member"
            db.commit()
        assert client.get("/admin/system/configuration", headers=headers).status_code == 403


def test_connect_csrf_approval_idempotency_and_offline_rejection():
    with TestClient(app) as client:
        headers = login(client)
        assert client.post("/admin/system/configuration", json=request()).status_code == 403
        for field, value in [
            ("shell", "/arbitrary/executable"),
            ("power", True),
            ("services", [{"unit": "unapproved.service", "scope": "system", "actions": ["stop"]}]),
        ]:
            bad = {**CONFIGURATION, field: value}
            assert (
                client.post(
                    "/admin/system/configuration", headers=headers, json=request(configuration=bad)
                ).status_code
                == 422
            )
        first = client.post("/admin/system/configuration", headers=headers, json=request())
        assert first.status_code == 200
        second = client.post("/admin/system/configuration", headers=headers, json=request())
        assert first.json()["id"] == second.json()["id"]
        assert (
            client.post(
                "/admin/system/configuration", headers=headers, json=request("another-system-key")
            ).status_code
            == 409
        )
        with SessionLocal() as db:
            db.get(SystemProvisionControl, 1).last_seen_at = now() - timedelta(minutes=1)
            db.commit()
        assert (
            client.post(
                "/admin/system/configuration", headers=headers, json=request("offline-system-key")
            ).status_code
            == 409
        )


def test_manager_claim_rechecks_administrator_session_and_expiry():
    with TestClient(app) as client:
        headers = login(client)
        job = client.post("/admin/system/configuration", headers=headers, json=request()).json()
        assert client.get("/system-manager/work").status_code == 401
        assert client.get("/system-manager/work", headers=MANAGER).json()["job"]["id"] == job["id"]
        client.post("/auth/logout", headers=headers)
        response = client.post(
            "/system-manager/report",
            headers=MANAGER,
            json={"inventory": INVENTORY, "job_id": job["id"], "state": "applying"},
        )
        assert response.json()["accepted"] is False
        with SessionLocal() as db:
            assert db.get(SystemProvisionJob, job["id"]).state == "failed"
            assert db.get(SystemControl, 1) is None


def test_connect_completes_only_after_authenticated_readings_and_disconnect_revokes():
    with TestClient(app) as client:
        headers = login(client)
        job = client.post("/admin/system/configuration", headers=headers, json=request()).json()
        report = {"inventory": INVENTORY, "job_id": job["id"], "state": "applying"}
        assert client.post("/system-manager/report", headers=MANAGER, json=report).json()[
            "accepted"
        ]
        report["state"] = "completed"
        assert (
            client.post("/system-manager/report", headers=MANAGER, json=report).status_code == 409
        )
        policy = {**CONFIGURATION, "account": "owner"}
        with SessionLocal() as db:
            db.add(SystemControl(id=1, token_hash=token_hash("runtime-token"), policy=policy))
            db.commit()
        broker.connected, broker.seen, broker.credential = (
            True,
            monotonic(),
            token_hash("runtime-token"),
        )
        broker.snapshot = Snapshot.model_validate(
            {
                "boot_id": "fixture-boot",
                "collected_at": now(),
                "identity": {
                    "hostname": "fixture",
                    "os": "Linux",
                    "kernel": "6-test",
                    "architecture": "x86_64",
                    "boot_time": now(),
                    "uptime_seconds": 10,
                },
                "compute": {},
                "memory": {},
                "capabilities": policy,
            }
        )
        assert client.post("/system-manager/report", headers=MANAGER, json=report).json()[
            "accepted"
        ]
        with SessionLocal() as db:
            db.get(SystemProvisionControl, 1).last_seen_at = now() - timedelta(minutes=1)
            db.commit()
        response = client.post(
            "/admin/system/configuration",
            headers=headers,
            json=request("disconnect-system-key", action="disconnect"),
        )
        assert response.status_code == 200
        assert not broker.connected
        assert broker.snapshot is None
        with SessionLocal() as db:
            assert db.get(SystemControl, 1).token_hash is None
            assert db.get(SystemProvisionControl, 1).configuration == CONFIGURATION
