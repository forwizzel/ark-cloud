import errno
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.local_storage import get_storage
from app.core.config import Settings, get_settings
from app.main import app
from app.models import LocalUser
from app.services.local_storage import LocalStorage, Manifest, RootConfig, StorageError, revision


def test_openat2_rejects_real_nested_mount():
    from app.services.local_storage import DIRECTORY, open_beneath

    fd = os.open("/", DIRECTORY)
    try:
        with pytest.raises(OSError) as failure:
            open_beneath(fd, "proc")
        assert failure.value.errno == errno.EXDEV
    finally:
        os.close(fd)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    info = tmp_path.stat()
    config = RootConfig.model_construct(
        id="personal",
        label="My files",
        path=str(tmp_path),
        device=info.st_dev,
        inode=info.st_ino,
        kind="managed",
        owner=None,
        read_only=False,
    )
    manifest = Manifest.model_construct(roots=[config])
    service = LocalStorage(manifest)
    monkeypatch.setattr("app.services.local_storage.mount_points", lambda: {str(tmp_path)})
    monkeypatch.setattr("app.api.local_storage.load_manifest", lambda _: manifest)
    app.dependency_overrides[get_storage] = lambda: service
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="sqlite://", storage_upload_max_bytes=64
    )
    with service.root("personal", "ark", provision=True):
        pass
    return service, tmp_path


def login(client):
    response = client.post("/auth/login", json={"username": "ark", "password": "test-password"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_file_workflow_and_conflicts(storage):
    client = TestClient(app)
    headers = login(client)
    assert client.get("/storage/roots").json()["roots"][0]["state"] == "healthy"
    assert (
        client.post("/storage/personal/folders", json={"path": "docs"}, headers=headers).status_code
        == 201
    )
    url = "/storage/personal/upload?path=docs/hello.txt"
    upload_headers = {**headers, "Content-Type": "application/octet-stream"}
    assert client.post(url, content=b"hello", headers=upload_headers).status_code == 201
    assert client.post(url, content=b"overwrite", headers=upload_headers).status_code == 409
    entries = client.get("/storage/personal/items?path=docs").json()["items"]
    file = entries[0]
    response = client.get(
        "/storage/personal/download", params={"path": file["path"], "revision": file["revision"]}
    )
    assert response.content == b"hello"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in response.headers["content-disposition"]
    moved = client.post(
        "/storage/personal/move",
        json={"path": file["path"], "destination": "new.txt", "revision": file["revision"]},
        headers=headers,
    )
    assert moved.status_code == 204
    entries = client.get("/storage/personal/items").json()["items"]
    for item in entries:
        assert (
            client.delete(
                "/storage/personal/items",
                params={"path": item["path"], "revision": item["revision"], "confirm": True},
                headers=headers,
            ).status_code
            == 204
        )
    assert client.get("/storage/personal/items").json()["items"] == []


def test_auth_csrf_and_private_roots(storage):
    service, path = storage
    client = TestClient(app)
    assert client.get("/storage/roots").status_code == 401
    login(client)
    assert client.post("/storage/personal/folders", json={"path": "denied"}).status_code == 403
    with service.root("personal", "other", provision=True) as fd:
        file = os.open("private", os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=fd)
        os.close(file)
    assert client.get("/storage/personal/items").json()["items"] == []
    assert client.get("/storage/unknown/items").status_code == 404
    assigned = service.manifest.roots[0].model_copy(
        update={"kind": "assigned", "owner": "other", "id": "external"}
    )
    service.manifest = Manifest.model_construct(roots=[assigned])
    assert client.get("/storage/roots").json()["roots"] == []
    assert client.get("/storage/external/items").status_code == 404


def test_assigned_read_only_root_rejects_other_accounts_and_all_writes(storage, db_session):
    service, path = storage
    (path / "ark").rmdir()  # This case exposes the assigned tree, not the managed fixture.
    member_id = str(uuid4())
    from argon2 import PasswordHasher

    db_session.add(
        LocalUser(
            id=member_id,
            username="member",
            password_hash=PasswordHasher().hash("member-password"),
            role="member",
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    config = service.manifest.roots[0].model_copy(
        update={"id": "photos", "kind": "assigned", "owner": member_id, "read_only": True}
    )
    service.manifest = Manifest.model_construct(roots=[config])
    (path / "family-photo.jpg").write_bytes(b"photo")
    admin = TestClient(app)
    login(admin)
    assert admin.get("/storage/roots").json()["roots"] == []
    assert admin.get("/storage/photos/items").status_code == 404
    member = TestClient(app)
    result = member.post("/auth/login", json={"username": "member", "password": "member-password"})
    assert result.status_code == 200
    csrf = {"X-CSRF-Token": result.json()["csrf_token"]}
    listed = member.get("/storage/photos/items")
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["name"] == "family-photo.jpg"
    downloaded = member.get(
        "/storage/photos/download", params={"path": item["path"], "revision": item["revision"]}
    )
    assert downloaded.content == b"photo"
    assert (
        member.post("/storage/photos/folders", json={"path": "blocked"}, headers=csrf).status_code
        == 403
    )
    assert (
        member.post(
            "/storage/photos/upload?path=new.jpg",
            content=b"contents",
            headers={**csrf, "Content-Type": "application/octet-stream"},
        ).status_code
        == 403
    )
    assert (
        member.delete(
            "/storage/photos/items",
            params={"path": item["path"], "revision": item["revision"], "confirm": True},
            headers=csrf,
        ).status_code
        == 403
    )
    assert (path / "family-photo.jpg").read_bytes() == b"photo"


@pytest.mark.parametrize(
    "path",
    ["../outside", "/etc/passwd", "a/../../etc", "a//b", ".ark-upload-test", "a\\b", "a/./b"],
)
def test_traversal_rejected(storage, path):
    client = TestClient(app)
    headers = login(client)
    assert (
        client.post("/storage/personal/folders", json={"path": path}, headers=headers).status_code
        == 422
    )


def test_symlink_hardlink_special_and_stale_items(storage, tmp_path):
    service, path = storage
    with service.root("personal", "ark"):
        pass
    home = path / "ark"
    (home / "link").symlink_to("/etc/passwd")
    (home / "dirlink").symlink_to("/tmp", target_is_directory=True)
    os.mkfifo(home / "pipe")
    (home / "original").write_text("one")
    os.link(home / "original", home / "hardlink")
    listing = service.listing("personal", "ark", "", 0, None)
    assert listing["items"] == []
    assert listing["skipped_count"] == 5
    for name in ["link", "dirlink", "pipe", "hardlink"]:
        with pytest.raises((StorageError, OSError)):
            service.download("personal", "ark", name, "0" * 32)
    (home / "file").write_text("before")
    old = revision((home / "file").stat())
    (home / "file").write_text("changed")
    with pytest.raises(StorageError, match="changed"):
        service.delete("personal", "ark", "file", old)
    assert (home / "file").read_text() == "changed"


def test_no_overwrite_and_nonempty_folder_deletion(storage):
    service, path = storage
    service.mkdir("personal", "ark", "folder")
    (path / "ark/folder/file").write_text("retained")
    with pytest.raises(OSError):
        service.delete("personal", "ark", "folder", revision((path / "ark/folder").stat()))
    (path / "ark/target").write_text("original")
    with pytest.raises(FileExistsError):
        service.move(
            "personal", "ark", "folder/file", "target", revision((path / "ark/folder/file").stat())
        )
    assert (path / "ark/target").read_text() == "original"


def test_missing_mount_identity_and_read_only(storage, monkeypatch):
    service, path = storage
    config = service.manifest.roots[0]
    service.manifest.roots[0] = config.model_copy(update={"inode": config.inode + 1})
    assert service.locations("ark")["roots"][0]["state"] == "unavailable"
    service.manifest.roots[0] = config.model_copy(update={"read_only": True})
    with pytest.raises(StorageError, match="read-only"):
        service.mkdir("personal", "ark", "denied")
    service.manifest.roots[0] = config
    monkeypatch.setattr("app.services.local_storage.mount_points", set)
    with pytest.raises(StorageError, match="mount is missing"):
        service.mkdir("personal", "ark", "denied")
    assert list((path / "ark").iterdir()) == []


def test_upload_limit_cleanup_and_revocation(storage, monkeypatch):
    client = TestClient(app)
    headers = {**login(client), "Content-Type": "application/octet-stream"}
    assert (
        client.post(
            "/storage/personal/upload?path=large", content=b"x" * 65, headers=headers
        ).status_code
        == 413
    )

    def revoked(*_):
        raise StorageError("Session expired", 401)

    monkeypatch.setattr("app.api.local_storage.still_authorized", revoked)
    assert (
        client.post(
            "/storage/personal/upload?path=revoked", content=b"x", headers=headers
        ).status_code
        == 401
    )
    assert list((storage[1] / "ark").iterdir()) == []


def test_paginated_directory_change(storage):
    service, path = storage
    with service.root("personal", "ark"):
        pass
    for i in range(101):
        (path / "ark" / str(i)).touch()
    page = service.listing("personal", "ark", "", 0, None)
    assert len(page["items"]) == 100
    assert page["next_offset"] == 100
    (path / "ark/new").touch()
    with pytest.raises(StorageError, match="changed"):
        service.listing("personal", "ark", "", 100, page["revision"])


def test_disk_full_and_chunked_limit_remove_partial_upload(storage, monkeypatch):
    client = TestClient(app)
    headers = {**login(client), "Content-Type": "application/octet-stream"}

    def chunks():
        yield b"x" * 64
        yield b"y"

    response = client.post(
        "/storage/personal/upload?path=too-large", content=chunks(), headers=headers
    )
    assert response.status_code == 413

    def full(*_):
        raise OSError(errno.ENOSPC, "test disk full")

    monkeypatch.setattr("app.api.local_storage.write_all", full)
    response = client.post("/storage/personal/upload?path=full", content=b"x", headers=headers)
    assert response.status_code == 507
    assert list((storage[1] / "ark").iterdir()) == []


def test_upload_does_not_publish_into_replaced_parent(storage, monkeypatch):
    import app.api.local_storage as routes

    original_publish = routes.publish
    service, path = storage
    service.mkdir("personal", "ark", "target")

    def replace_parent(*args):
        (path / "ark/target").rename(path / "ark/moved")
        (path / "ark/target").mkdir()
        original_publish(*args)

    monkeypatch.setattr(routes, "publish", replace_parent)
    client = TestClient(app)
    headers = {**login(client), "Content-Type": "application/octet-stream"}
    assert (
        client.post(
            "/storage/personal/upload?path=target/file", content=b"x", headers=headers
        ).status_code
        == 409
    )
    assert list((path / "ark/target").iterdir()) == []
    assert list((path / "ark/moved").iterdir()) == []


def test_disabled_user_loses_access_but_files_survive(storage, db_session):
    from app.models import LocalUser

    client = TestClient(app)
    headers = login(client)
    client.post("/storage/personal/folders", json={"path": "keep"}, headers=headers)
    user = db_session.get(LocalUser, "ark")
    user.active = False
    db_session.commit()
    assert client.get("/storage/personal/items").status_code == 401
    assert (storage[1] / "ark/keep").is_dir()


def test_manifest_is_bounded_and_rejects_unapproved_targets(tmp_path):
    from app.services.local_storage import load_manifest

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"version":1,"roots":[{"id":"escape","path":"/","device":1,"inode":2,"label":"Bad","owner":"ark"}]}'
    )
    with pytest.raises(StorageError, match="configuration is invalid"):
        load_manifest(str(manifest))
    manifest.write_bytes(b" " * 65_537)
    with pytest.raises(StorageError, match="configuration is invalid"):
        load_manifest(str(manifest))
