import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.storage_admin import begin_setup
from app.auth.service import token_hash
from app.core.config import Settings, get_settings
from app.main import app
from app.models import LocalUser, StorageControl, StorageJob
from app.services.local_storage import LocalStorage, Manifest, RootConfig, StorageError


def sign_in(client):
    result = client.post("/auth/login", json={"username": "ark", "password": "test-password"})
    return {"X-CSRF-Token": result.json()["csrf_token"]}


@pytest.fixture
def manager(db_session):
    token = "test-manager-credential-" + "x" * 48
    value = StorageControl(
        id=1,
        token_hash=token_hash(token),
        snapshot={"roots": []},
        blocked_roots=[],
        last_seen_at=datetime.now(UTC),
    )
    db_session.add(value)
    db_session.commit()
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def private_storage(tmp_path, monkeypatch):
    config = RootConfig.model_construct(
        id="personal",
        label="My files",
        path=str(tmp_path),
        device=tmp_path.stat().st_dev,
        inode=tmp_path.stat().st_ino,
        kind="managed",
        owner=None,
        read_only=False,
    )
    manifest = Manifest.model_construct(roots=[config])
    monkeypatch.setattr("app.services.local_storage.mount_points", lambda: {str(tmp_path)})
    monkeypatch.setattr("app.api.storage_admin.load_manifest", lambda _: manifest)
    monkeypatch.setattr("app.api.local_storage.load_manifest", lambda _: manifest)
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="sqlite://", storage_upload_max_bytes=64
    )
    return tmp_path, manifest


def test_admin_and_manager_authentication_and_csrf(manager, db_session):
    client = TestClient(app)
    assert client.get("/admin/storage").status_code == 401
    csrf = sign_in(client)
    assert client.get("/admin/storage").status_code == 403
    assert client.get("/admin/storage", headers=csrf).status_code == 200
    assert client.post("/admin/storage/jobs", json={"action": "browse"}).status_code == 403
    assert client.get("/storage-manager/work", headers=csrf).status_code == 401
    assert client.get("/storage-manager/work", headers=manager).status_code == 200
    user = db_session.get(LocalUser, "ark")
    user.role = "member"
    db_session.commit()
    assert client.get("/admin/storage", headers=csrf).status_code == 403
    assert (
        client.put(
            "/admin/storage/settings", headers=csrf, json={"upload_max_bytes": 10}
        ).status_code
        == 403
    )


def test_admin_inventory_remains_available_when_manifest_unreadable(
    manager, db_session, monkeypatch
):
    value = db_session.get(StorageControl, 1)
    value.snapshot = {
        "roots": [
            {
                "id": "photos",
                "label": "Photos",
                "source": "/disk/photos",
                "path": "/srv/ark-storage/photos",
                "device": 1,
                "inode": 2,
                "kind": "assigned",
                "owner": "ark",
                "read_only": True,
                "selinux": "preserve",
            }
        ]
    }
    db_session.commit()

    def unreadable(_):
        raise StorageError("Storage configuration is invalid.", 503)

    monkeypatch.setattr("app.api.storage_admin.load_manifest", unreadable)
    client = TestClient(app)
    csrf = sign_in(client)
    response = client.get("/admin/storage", headers=csrf)
    assert response.status_code == 200
    data = response.json()
    assert "manifest" in data["configuration_error"]
    assert data["roots"][0]["state"] == "unavailable"
    assert data["roots"][0]["message"] == data["configuration_error"]
    assert data["manager"]["enrolled"]
    assert data["users"][0]["username"] == "ark"
    assert (
        client.post(
            "/admin/storage/jobs",
            json={"action": "remove", "root_id": "photos", "confirmed": True},
            headers=csrf,
        ).status_code
        == 503
    )


def test_status_reads_never_create_private_directories(private_storage):
    path, _ = private_storage
    client = TestClient(app)
    csrf = sign_in(client)
    assert client.get("/storage/roots").json()["roots"][0]["state"] == "unavailable"
    assert client.get("/storage/preferences").json()["root_id"] is None
    assert not (path / "ark").exists()
    assert client.post("/storage/private-folder", headers=csrf).status_code == 200
    assert (path / "ark").is_dir()
    assert client.get("/storage/roots").json()["roots"][0]["state"] == "healthy"


def test_preferences_are_validated_and_isolated(private_storage, db_session):
    path, manifest = private_storage
    client = TestClient(app)
    csrf = sign_in(client)
    client.post("/storage/private-folder", headers=csrf)
    (path / "ark/docs").mkdir()
    assert (
        client.put(
            "/storage/preferences", json={"root_id": "personal", "path": "../outside"}, headers=csrf
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/storage/preferences", json={"root_id": "personal", "path": "missing"}, headers=csrf
        ).status_code
        == 404
    )
    saved = client.put(
        "/storage/preferences", json={"root_id": "personal", "path": "docs"}, headers=csrf
    )
    assert saved.json()["path"] == "docs"
    assert client.get("/storage/preferences").json()["root_id"] == "personal"
    manifest.roots[0] = manifest.roots[0].model_copy(
        update={"kind": "assigned", "owner": "another"}
    )
    assert (
        client.put(
            "/storage/preferences", json={"root_id": "personal", "path": ""}, headers=csrf
        ).status_code
        == 404
    )
    # A stale saved preference is retained for the UI to explain; it grants no access.
    assert client.get("/storage/preferences").json()["path"] == "docs"
    assert client.get("/storage/personal/items").status_code == 404
    assert (
        client.put("/storage/preferences", json={"root_id": None}, headers=csrf).json()["root_id"]
        is None
    )


def test_upload_policy_applies_at_runtime_and_is_server_enforced(private_storage):
    client = TestClient(app)
    csrf = sign_in(client)
    client.post("/storage/private-folder", headers=csrf)
    assert (
        client.put(
            "/admin/storage/settings", json={"upload_max_bytes": 3}, headers=csrf
        ).status_code
        == 200
    )
    assert client.get("/storage/preferences").json()["upload_max_bytes"] == 3
    headers = {**csrf, "Content-Type": "application/octet-stream"}
    assert (
        client.post(
            "/storage/personal/upload?path=too-large", content=b"1234", headers=headers
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/storage/personal/upload?path=allowed", content=b"123", headers=headers
        ).status_code
        == 201
    )
    assert (
        client.put(
            "/admin/storage/settings", json={"upload_max_bytes": 10 * 1024**3 + 1}, headers=csrf
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/admin/storage/settings", json={"upload_max_bytes": None}, headers=csrf
        ).status_code
        == 200
    )
    assert client.get("/storage/preferences").json()["upload_max_bytes"] == 64


def test_jobs_require_confirmation_valid_account_and_idle_manager(manager, db_session):
    client = TestClient(app)
    csrf = sign_in(client)
    body = {
        "action": "add",
        "path": "/disk/photos",
        "label": "Photos",
        "owner": "missing",
        "confirmed": True,
    }
    assert client.post("/admin/storage/jobs", json=body, headers=csrf).status_code == 422
    owner = str(uuid4())
    db_session.add(
        LocalUser(
            id=owner,
            username="invited",
            role="member",
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    body["owner"] = owner
    assert (
        client.post(
            "/admin/storage/jobs", json={**body, "confirmed": False}, headers=csrf
        ).status_code
        == 422
    )
    accepted = client.post("/admin/storage/jobs", json=body, headers=csrf)
    assert accepted.status_code == 202
    assert accepted.json()["payload"]["root_id"].startswith("folder-")
    assert client.post("/admin/storage/jobs", json=body, headers=csrf).status_code == 409
    work = client.get("/storage-manager/work", headers=manager).json()["job"]
    assert work["id"] == accepted.json()["id"]


def test_canceled_and_demoted_requests_cannot_be_claimed(manager, db_session):
    client = TestClient(app)
    csrf = sign_in(client)
    operation = {"action": "init", "path": "/disk/private", "label": "Private", "confirmed": True}
    job = client.post("/admin/storage/jobs", json=operation, headers=csrf).json()
    assert client.get("/storage-manager/work", headers=manager).json()["job"]["state"] == "queued"
    assert client.post(f"/admin/storage/jobs/{job['id']}/cancel", headers=csrf).status_code == 200
    claim = {
        "roots": [],
        "approved_paths": ["/disk"],
        "generation": "test",
        "job_id": job["id"],
        "state": "applying",
    }
    assert (
        client.post("/storage-manager/report", json=claim, headers=manager).json()["accepted"]
        is False
    )
    assert client.get("/storage-manager/work", headers=manager).json()["job"] is None
    job = client.post("/admin/storage/jobs", json=operation, headers=csrf).json()
    user = db_session.get(LocalUser, "ark")
    user.role = "member"
    db_session.commit()
    claim["job_id"] = job["id"]
    assert client.post("/storage-manager/report", json=claim, headers=manager).status_code == 403
    assert client.get("/storage-manager/work", headers=manager).json()["job"] is None


def test_recipient_is_revalidated_before_claim(manager, db_session):
    client = TestClient(app)
    csrf = sign_in(client)
    owner = str(uuid4())
    db_session.add(
        LocalUser(
            id=owner,
            username="recipient",
            role="member",
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    job = client.post(
        "/admin/storage/jobs",
        json={
            "action": "add",
            "owner": owner,
            "path": "/disk/photos",
            "label": "Photos",
            "confirmed": True,
        },
        headers=csrf,
    ).json()
    user = db_session.get(LocalUser, owner)
    user.active = False
    db_session.commit()
    claim = {
        "roots": [],
        "approved_paths": ["/disk"],
        "generation": "test",
        "job_id": job["id"],
        "state": "applying",
    }
    assert client.post("/storage-manager/report", json=claim, headers=manager).status_code == 409
    assert client.get("/storage-manager/work", headers=manager).json()["job"] is None


def test_disconnect_revokes_access_before_unmount_and_blocks_upload_publish(
    manager, private_storage, db_session
):
    path, manifest = private_storage
    config = manifest.roots[0].model_copy(
        update={"kind": "assigned", "owner": "ark", "id": "photos"}
    )
    manifest.roots = [config]
    value = db_session.get(StorageControl, 1)
    value.snapshot = {
        "roots": [{**config.model_dump(), "source": "/disk/photos", "selinux": "preserve"}]
    }
    db_session.commit()
    (path / "keep").write_text("preserve")
    client = TestClient(app)
    csrf = sign_in(client)
    assert client.get("/storage/photos/items").status_code == 200
    response = client.post(
        "/admin/storage/jobs",
        json={"action": "remove", "root_id": "photos", "confirmed": True},
        headers=csrf,
    )
    assert response.status_code == 202
    assert client.get("/storage/photos/items").status_code == 404
    with pytest.raises(StorageError):
        LocalStorage(manifest).config("photos", "ark")
    assert (path / "keep").read_text() == "preserve"


def test_manager_cannot_claim_completion_without_applied_mounts(manager, db_session):
    client = TestClient(app)
    csrf = sign_in(client)
    job = client.post(
        "/admin/storage/jobs",
        json={"action": "init", "path": "/disk/ark", "label": "Private", "confirmed": True},
        headers=csrf,
    ).json()
    root = {
        "id": "personal",
        "label": "Private",
        "path": "/srv/ark-storage/personal",
        "device": 1,
        "inode": 2,
        "kind": "managed",
        "owner": None,
        "read_only": False,
        "source": "/disk/ark",
        "selinux": "private",
    }
    report = {
        "roots": [root],
        "approved_paths": ["/disk"],
        "generation": "test",
        "job_id": job["id"],
        "state": "completed",
        "message": "Connected",
    }
    assert client.post("/storage-manager/report", json=report, headers=manager).status_code == 409
    db_session.expire_all()
    assert db_session.get(StorageJob, job["id"]).state != "completed"


def test_report_verifies_mounts_and_retries_without_losing_operation_identity(
    manager, monkeypatch, db_session, tmp_path
):
    client = TestClient(app)
    csrf = sign_in(client)
    manifest = Manifest(roots=[])
    monkeypatch.setattr("app.api.storage_admin.load_manifest", lambda _: manifest)
    job = client.post(
        "/admin/storage/jobs",
        json={"action": "init", "path": "/disk/ark", "label": "Private", "confirmed": True},
        headers=csrf,
    ).json()
    report = {
        "roots": [],
        "approved_paths": ["/disk"],
        "generation": "test",
        "job_id": job["id"],
        "state": "failed",
        "message": "Interrupted",
        "result": {},
    }
    assert client.post("/storage-manager/report", json=report, headers=manager).status_code == 200
    retried = client.post(f"/admin/storage/jobs/{job['id']}/retry", headers=csrf).json()
    assert retried["payload"]["root_id"] == "personal"
    assert retried["payload"]["resume_id"] == job["id"]
    root = RootConfig(
        id="personal",
        label="Private",
        path="/srv/ark-storage/personal",
        device=1,
        inode=2,
        kind="managed",
    )
    manifest.roots = [root]

    @contextmanager
    def unavailable(*args, **kwargs):
        raise StorageError("Mount is missing", 503)
        yield

    monkeypatch.setattr(LocalStorage, "root", unavailable)
    report.update(
        roots=[{**root.model_dump(), "source": "/disk/ark", "selinux": "private"}],
        job_id=retried["id"],
        state="completed",
    )
    assert client.post("/storage-manager/report", json=report, headers=manager).status_code == 503

    @contextmanager
    def mounted(*args, **kwargs):
        fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            yield fd
        finally:
            os.close(fd)

    monkeypatch.setattr(LocalStorage, "root", mounted)
    assert client.post("/storage-manager/report", json=report, headers=manager).status_code == 200
    assert client.get("/admin/storage", headers=csrf).json()["jobs"][0]["state"] == "completed"


def failed_job(db, action="update", root_id="gone", **result):
    job = StorageJob(
        id=str(uuid4()),
        principal_id="ark",
        action=action,
        payload={"root_id": root_id, "path": "/disk/private"},
        state="failed",
        message="Old operation failed.",
        result=result,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(job)
    db.commit()
    return job


def test_obsolete_failures_and_dismissal_do_not_release_access(manager, db_session):
    job = failed_job(db_session)
    value = db_session.get(StorageControl, 1)
    value.blocked_roots = ["gone"]
    db_session.commit()
    client = TestClient(app)
    csrf = sign_in(client)
    view = client.get("/admin/storage", headers=csrf).json()["jobs"][0]
    assert view["disposition"] == "obsolete"
    assert not view["can_retry"]
    assert client.post(f"/admin/storage/jobs/{job.id}/retry", headers=csrf).status_code == 409
    assert client.post(f"/admin/storage/jobs/{job.id}/dismiss").status_code == 403
    assert client.post(f"/admin/storage/jobs/{job.id}/dismiss", headers=csrf).status_code == 200
    db_session.expire_all()
    assert db_session.get(StorageControl, 1).blocked_roots == ["gone"]
    assert (
        client.get("/admin/storage", headers=csrf).json()["jobs"][0]["disposition"] == "dismissed"
    )


def test_bulk_dismiss_only_history_and_not_unfinished_or_current_failures(manager, db_session):
    old = failed_job(db_session)
    attention = failed_job(db_session, action="init", root_id="personal")
    client = TestClient(app)
    csrf = sign_in(client)
    assert client.post("/admin/storage/jobs/dismiss-history", headers=csrf).status_code == 200
    db_session.expire_all()
    assert db_session.get(StorageJob, old.id).result.get("dismissed_at")
    assert not db_session.get(StorageJob, attention.id).result.get("dismissed_at")
    active = begin_setup(db_session, "/disk/private", "personal")
    assert (
        client.post(f"/admin/storage/jobs/{active['id']}/dismiss", headers=csrf).status_code == 409
    )
    assert client.get("/storage-manager/work", headers=manager).json()["job"] is None


def test_idle_reconciliation_requires_manifest_match_and_absent_mounts(
    manager, db_session, monkeypatch
):
    job = failed_job(db_session, action="remove")
    value = db_session.get(StorageControl, 1)
    value.blocked_roots = ["gone", "mounted"]
    db_session.commit()
    manifest = Manifest(roots=[])
    monkeypatch.setattr("app.api.storage_admin.load_manifest", lambda _: manifest)
    monkeypatch.setattr("app.api.storage_admin.mount_points", lambda: {"/srv/ark-storage/mounted"})
    client = TestClient(app)
    body = {"roots": [], "approved_paths": [], "generation": "test"}
    assert client.post("/storage-manager/reconcile", json=body).status_code == 401
    assert client.post("/storage-manager/reconcile", json=body, headers=manager).status_code == 200
    db_session.expire_all()
    assert db_session.get(StorageControl, 1).blocked_roots == ["mounted"]
    assert db_session.get(StorageJob, job.id).result["resolved"]
    manifest.roots = [
        RootConfig(
            id="personal",
            label="My files",
            path="/srv/ark-storage/personal",
            device=1,
            inode=2,
            kind="managed",
        )
    ]
    assert client.post("/storage-manager/reconcile", json=body, headers=manager).status_code == 409
    assert db_session.get(StorageControl, 1).blocked_roots == ["mounted"]


def test_host_setup_resumes_and_only_api_verification_can_mark_ready(
    manager, db_session, monkeypatch, tmp_path
):
    job = begin_setup(db_session, "/home/owner/Ark-Files", "personal")
    assert begin_setup(db_session, "/home/owner/Ark-Files", "personal")["id"] == job["id"]
    with pytest.raises(ValueError, match="active storage operation"):
        begin_setup(db_session, "/other/path", "personal")
    client = TestClient(app)
    csrf = sign_in(client)
    assert (
        client.post("/admin/storage/jobs", json={"action": "setup"}, headers=csrf).status_code
        == 422
    )
    root = RootConfig(
        id="personal",
        label="My files",
        path="/srv/ark-storage/personal",
        device=1,
        inode=2,
        kind="managed",
    )
    manifest = Manifest(roots=[root])
    monkeypatch.setattr("app.api.storage_admin.load_manifest", lambda _: manifest)
    body = {
        "roots": [{**root.model_dump(), "source": "/home/owner/Ark-Files", "selinux": "private"}],
        "approved_paths": ["/home/owner/Ark-Files"],
        "generation": "test",
        "job_id": job["id"],
        "state": "completed",
        "message": "Ready",
    }

    @contextmanager
    def denied(*args, **kwargs):
        raise StorageError("Permission denied", 503)
        yield

    monkeypatch.setattr(LocalStorage, "root", denied)
    assert client.post("/storage-manager/report", json=body, headers=manager).status_code == 503
    db_session.expire_all()
    assert db_session.get(StorageJob, job["id"]).state == "applying"
    assert db_session.get(StorageControl, 1).blocked_roots == ["personal"]

    @contextmanager
    def mounted(self, root_id, owner, *, base=False, provision=False, **kwargs):
        path = tmp_path if base else tmp_path / owner
        if provision:
            path.mkdir(exist_ok=True)
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            yield fd
        finally:
            os.close(fd)

    monkeypatch.setattr(LocalStorage, "root", mounted)
    assert client.post("/storage-manager/report", json=body, headers=manager).status_code == 200
    assert (tmp_path / "ark").is_dir()
    assert not list((tmp_path / "ark").iterdir())
    db_session.expire_all()
    assert db_session.get(StorageControl, 1).blocked_roots == []
    assert client.get("/admin/storage", headers=csrf).json()["setup"]["job"]["state"] == "completed"


def test_stalled_setup_exposes_resume_guidance_without_abandoning_work(manager, db_session):
    job = begin_setup(db_session, "/disk/private", "personal")
    stored = db_session.get(StorageJob, job["id"])
    stored.updated_at = datetime.now(UTC) - timedelta(minutes=6)
    db_session.commit()
    client = TestClient(app)
    csrf = sign_in(client)
    data = client.get("/admin/storage", headers=csrf).json()
    assert data["setup"]["interrupted"]
    assert data["setup"]["job"]["state"] == "applying"
    assert client.post(f"/admin/storage/jobs/{job['id']}/dismiss", headers=csrf).status_code == 409
    assert begin_setup(db_session, "/disk/private", "personal")["id"] == job["id"]


def test_connecting_failed_registered_path_becomes_repair_and_restores_initial_intent(
    manager, db_session, monkeypatch, tmp_path
):
    root = RootConfig(
        id="second",
        label="Second",
        path="/srv/ark-storage/second",
        kind="shared",
        device=1,
        inode=2,
        registration=str(uuid4()),
    )
    source = {**root.model_dump(), "source": "/host/second", "selinux": "preserve"}
    value = db_session.get(StorageControl, 1)
    value.snapshot = {"roots": [source]}
    value.blocked_roots = ["second"]
    original = StorageJob(
        id=str(uuid4()),
        principal_id="ark",
        action="add",
        state="failed",
        payload={
            "root_id": "second",
            "path": "/host/second",
            "grants": [{"user_id": "ark", "level": "write"}],
            "grant_access": False,
        },
        message="Write access denied",
        result={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(original)
    db_session.commit()
    monkeypatch.setattr("app.api.storage_admin.load_manifest", lambda _: Manifest(roots=[root]))
    client = TestClient(app)
    csrf = sign_in(client)
    response = client.post(
        "/admin/storage/jobs",
        headers=csrf,
        json={
            "action": "add",
            "label": "Second",
            "path": "/host/second",
            "shared": True,
            "confirmed": True,
        },
    )
    assert response.status_code == 202
    job = response.json()
    assert job["action"] == "repair"
    assert job["payload"]["root_id"] == "second"
    assert job["payload"]["automatic_access"]
    assert job["payload"]["restore_grants"]
    assert job["payload"]["grants"] == original.payload["grants"]

    @contextmanager
    def mounted(*args, **kwargs):
        fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            yield fd
        finally:
            os.close(fd)

    monkeypatch.setattr(LocalStorage, "root", mounted)
    report = {
        "roots": [source],
        "approved_paths": ["/host/second"],
        "generation": "test",
        "job_id": job["id"],
        "state": "completed",
        "message": "Connected",
    }
    assert client.post("/storage-manager/report", headers=manager, json=report).status_code == 200
    db_session.expire_all()
    assert db_session.get(StorageControl, 1).blocked_roots == []
    from app.models import StorageGrant

    assert db_session.get(StorageGrant, (root.registration, "ark")).level == "write"


def test_retry_upgrades_stale_access_checkbox_to_automatic_repair(manager, db_session, monkeypatch):
    root = RootConfig(
        id="second",
        label="Second",
        path="/srv/ark-storage/second",
        kind="shared",
        device=1,
        inode=2,
        registration=str(uuid4()),
    )
    value = db_session.get(StorageControl, 1)
    value.snapshot = {
        "roots": [{**root.model_dump(), "source": "/host/second", "selinux": "preserve"}]
    }
    value.blocked_roots = ["second"]
    job = failed_job(db_session, action="add", root_id="second")
    job.payload = {
        "action": "add",
        "root_id": "second",
        "path": "/host/second",
        "label": "Second",
        "shared": True,
        "grant_access": False,
        "grants": [{"user_id": "ark", "level": "write"}],
    }
    db_session.commit()
    monkeypatch.setattr("app.api.storage_admin.load_manifest", lambda _: Manifest(roots=[root]))
    client = TestClient(app)
    response = client.post(f"/admin/storage/jobs/{job.id}/retry", headers=sign_in(client))
    assert response.status_code == 202
    assert response.json()["action"] == "repair"
    assert response.json()["payload"]["automatic_access"]
    assert response.json()["payload"]["registration"] == root.registration


def test_existing_private_source_cannot_be_reclassified_by_connect(
    manager, private_storage, db_session
):
    _, manifest = private_storage
    value = db_session.get(StorageControl, 1)
    value.snapshot = {
        "roots": [
            {**manifest.roots[0].model_dump(), "source": "/host/private", "selinux": "private"}
        ]
    }
    db_session.commit()
    client = TestClient(app)
    response = client.post(
        "/admin/storage/jobs",
        headers=sign_in(client),
        json={
            "action": "add",
            "path": "/host/private",
            "label": "Shared",
            "shared": True,
            "grants": [{"user_id": "ark", "level": "write"}],
            "confirmed": True,
        },
    )
    assert response.status_code == 409
