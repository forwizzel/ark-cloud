import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.api.local_storage import publish
from app.auth.service import SESSION_COOKIE
from app.core.config import get_settings
from app.main import app
from app.models import LocalUser, StorageControl
from app.services.local_storage import LocalStorage, Manifest, RootConfig, StorageError


def user(db, name):
    account = LocalUser(
        id=str(uuid4()),
        username=name,
        role="member",
        active=True,
        password_hash=PasswordHasher().hash("member-password"),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(account)
    db.commit()
    return account


def login(name="ark", password="test-password"):
    client = TestClient(app)
    response = client.post("/auth/login", json={"username": name, "password": password})
    assert response.status_code == 200
    return client, {"X-CSRF-Token": response.json()["csrf_token"]}


@pytest.fixture
def shared(tmp_path, monkeypatch, db_session):
    member = user(db_session, "member")
    root = RootConfig.model_construct(
        id="files",
        label="Shared files",
        path=str(tmp_path),
        kind="shared",
        owner=None,
        device=tmp_path.stat().st_dev,
        inode=tmp_path.stat().st_ino,
        read_only=False,
        registration=str(uuid4()),
    )
    manifest = Manifest.model_construct(roots=[root])
    monkeypatch.setattr("app.services.local_storage.mount_points", lambda: {str(tmp_path)})
    monkeypatch.setattr("app.api.local_storage.load_manifest", lambda _: manifest)
    monkeypatch.setattr("app.api.storage_admin.load_manifest", lambda _: manifest)
    db_session.add(
        StorageControl(
            id=1,
            snapshot={
                "roots": [{**root.model_dump(), "source": "/host/shared", "selinux": "preserve"}]
            },
            blocked_roots=[],
        )
    )
    db_session.commit()
    return tmp_path, manifest, member


def grant(client, csrf, user_id, level):
    route = "/admin/storage/roots/files/access"
    current = client.get(route, headers=csrf)
    assert current.status_code == 200
    return client.put(
        route,
        headers=csrf,
        json={
            "user_id": user_id,
            "level": level,
            "revision": current.json()["revision"],
            "registration": current.json()["registration"],
        },
    )


def test_shared_grants_enforce_all_read_only_operations_and_preserve_revoked_files(shared):
    path, manifest, member = shared
    admin, csrf = login()
    reader, reader_csrf = login("member", "member-password")
    assert admin.get("/storage/roots").json()["roots"] == []
    assert reader.get("/storage/files/items").status_code == 404
    assert grant(admin, csrf, "ark", "write").status_code == 200
    assert grant(admin, csrf, member.id, "read").status_code == 200
    assert (
        admin.post(
            "/storage/files/upload?path=shared.txt",
            content=b"same content",
            headers={**csrf, "Content-Type": "application/octet-stream"},
        ).status_code
        == 201
    )
    item = reader.get("/storage/files/items").json()["items"][0]
    assert (
        reader.get(f"/storage/files/download?path=shared.txt&revision={item['revision']}").content
        == b"same content"
    )
    assert reader.get("/storage/roots").json()["roots"][0]["read_only"]
    assert (
        reader.post(
            "/storage/files/folders", json={"path": "denied"}, headers=reader_csrf
        ).status_code
        == 403
    )
    assert (
        reader.post(
            "/storage/files/move",
            json={"path": "shared.txt", "destination": "renamed.txt", "revision": item["revision"]},
            headers=reader_csrf,
        ).status_code
        == 403
    )
    assert (
        reader.delete(
            f"/storage/files/items?path=shared.txt&revision={item['revision']}&confirm=true",
            headers=reader_csrf,
        ).status_code
        == 403
    )
    assert (
        reader.post(
            "/storage/files/upload?path=denied",
            content=b"no",
            headers={**reader_csrf, "Content-Type": "application/octet-stream"},
        ).status_code
        == 403
    )
    assert grant(admin, csrf, member.id, "write").status_code == 200
    assert (
        reader.post(
            "/storage/files/folders", json={"path": "allowed"}, headers=reader_csrf
        ).status_code
        == 201
    )
    assert grant(admin, csrf, member.id, "none").status_code == 200
    assert reader.get("/storage/files/items").status_code == 404
    assert reader.get("/storage/roots").json()["roots"] == []
    assert (path / "shared.txt").read_bytes() == b"same content"


def test_access_requires_admin_csrf_and_optimistic_revision(shared):
    _, _, member = shared
    admin, csrf = login()
    client, member_csrf = login("member", "member-password")
    route = "/admin/storage/roots/files/access"
    assert client.get(route, headers=member_csrf).status_code == 403
    registration = admin.get(route, headers=csrf).json()["registration"]
    body = {"user_id": member.id, "level": "read", "revision": 0, "registration": registration}
    assert admin.put(route, json=body).status_code == 403
    assert grant(admin, csrf, member.id, "read").status_code == 200
    assert admin.put(route, headers=csrf, json={**body, "level": "write"}).status_code == 409
    assert admin.get(route, headers=csrf).json()["accounts"][1]["level"] == "read"


def test_private_access_preserves_existing_users_but_requires_explicit_grants_for_later_accounts(
    shared, db_session
):
    path, manifest, member = shared
    root = manifest.roots[0].model_copy(update={"kind": "managed"})
    manifest.roots = [root]
    value = db_session.get(StorageControl, 1)
    value.snapshot = {
        "roots": [{**root.model_dump(), "source": "/host/private", "selinux": "private"}]
    }
    db_session.commit()
    admin, csrf = login()
    initial = admin.get("/admin/storage/roots/files/access", headers=csrf).json()
    assert all(account["level"] == "write" for account in initial["accounts"])
    assert not list(path.iterdir())  # Status reads do not provision folders.
    later = user(db_session, "later")
    client, client_csrf = login("later", "member-password")
    assert client.get("/storage/roots").json()["roots"] == []
    assert grant(admin, csrf, later.id, "read").status_code == 200
    assert (path / later.id).is_dir()
    assert admin.post("/storage/private-folder", headers=csrf).status_code == 200
    (path / "ark" / "admin-only").write_text("private")
    (path / member.id).mkdir()
    (path / member.id / "member-only").write_text("private")
    assert client.get("/storage/files/items").json()["items"] == []
    assert [item["name"] for item in admin.get("/storage/files/items").json()["items"]] == [
        "admin-only"
    ]
    assert (
        client.post(
            "/storage/files/folders", json={"path": "denied"}, headers=client_csrf
        ).status_code
        == 403
    )
    assert client.get(f"/storage/files/items?path=../{member.id}").status_code == 422


def test_host_read_only_limit_and_disabled_accounts_override_grants(shared, db_session):
    _, manifest, member = shared
    admin, csrf = login()
    assert grant(admin, csrf, member.id, "write").status_code == 200
    root = manifest.roots[0].model_copy(update={"read_only": True})
    manifest.roots = [root]
    value = db_session.get(StorageControl, 1)
    value.snapshot = {
        "roots": [{**root.model_dump(), "source": "/host/shared", "selinux": "preserve"}]
    }
    db_session.commit()
    assert grant(admin, csrf, member.id, "write").status_code == 422
    client, member_csrf = login("member", "member-password")
    assert client.get("/storage/roots").json()["roots"][0]["read_only"]
    member.active = False
    db_session.commit()
    assert LocalStorage(manifest).locations(member.id)["roots"] == []
    assert grant(admin, csrf, member.id, "none").status_code == 200


def test_revocation_and_regrant_prevent_an_existing_upload_from_publishing(shared):
    path, manifest, member = shared
    admin, csrf = login()
    assert grant(admin, csrf, member.id, "write").status_code == 200
    client, _ = login("member", "member-password")
    original = LocalStorage(manifest)
    with original.root("files", member.id, write=True) as parent:
        fd = os.open(".ark-upload-test", os.O_CREAT | os.O_WRONLY, 0o600, dir_fd=parent)
        os.close(fd)
        assert grant(admin, csrf, member.id, "none").status_code == 200
        assert grant(admin, csrf, member.id, "write").status_code == 200
        request = SimpleNamespace(cookies={SESSION_COOKIE: client.cookies.get(SESSION_COOKIE)})
        with pytest.raises(StorageError, match="access changed"):
            publish(
                original,
                "files",
                member.id,
                "new.txt",
                parent,
                ".ark-upload-test",
                "new.txt",
                request,
                get_settings(),
            )
        os.unlink(".ark-upload-test", dir_fd=parent)
    assert not (path / "new.txt").exists()


def test_recreated_registration_never_inherits_old_shared_grants(shared, db_session):
    _, manifest, member = shared
    admin, csrf = login()
    assert grant(admin, csrf, member.id, "write").status_code == 200
    root = manifest.roots[0].model_copy(update={"registration": str(uuid4())})
    manifest.roots = [root]
    value = db_session.get(StorageControl, 1)
    value.snapshot = {
        "roots": [{**root.model_dump(), "source": "/host/new", "selinux": "preserve"}]
    }
    db_session.commit()
    client, _ = login("member", "member-password")
    assert client.get("/storage/files/items").status_code == 404
    assert client.get("/storage/roots").json()["roots"] == []


def test_private_base_cannot_silently_become_shared_under_the_same_registration(shared, db_session):
    _, manifest, member = shared
    root = manifest.roots[0].model_copy(update={"kind": "managed"})
    manifest.roots = [root]
    value = db_session.get(StorageControl, 1)
    value.snapshot = {
        "roots": [{**root.model_dump(), "source": "/host/private", "selinux": "private"}]
    }
    db_session.commit()
    admin, csrf = login()
    assert admin.get("/admin/storage/roots/files/access", headers=csrf).status_code == 200
    manifest.roots = [root.model_copy(update={"kind": "shared"})]
    client, _ = login("member", "member-password")
    assert client.get("/storage/files/items").status_code == 503


def test_stale_access_editor_cannot_grant_a_recreated_location(shared, db_session):
    _, manifest, member = shared
    admin, csrf = login()
    old = admin.get("/admin/storage/roots/files/access", headers=csrf).json()
    root = manifest.roots[0].model_copy(update={"registration": str(uuid4())})
    manifest.roots = [root]
    value = db_session.get(StorageControl, 1)
    value.snapshot = {
        "roots": [{**root.model_dump(), "source": "/host/new", "selinux": "preserve"}]
    }
    db_session.commit()
    assert (
        admin.put(
            "/admin/storage/roots/files/access",
            headers=csrf,
            json={
                "user_id": member.id,
                "level": "write",
                "revision": old["revision"],
                "registration": old["registration"],
            },
        ).status_code
        == 409
    )
