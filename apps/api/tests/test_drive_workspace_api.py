from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import (
    GoogleDriveActivity,
    GoogleDriveCatalogItem,
    GoogleDriveCatalogSync,
    GoogleDriveConnection,
    GoogleDriveParentEdge,
    GoogleDrivePinnedLocation,
    GoogleDriveSyncAttempt,
)
from app.services.drive_workspace import DriveWorkspace

client = TestClient(app)
FOLDER = "application/vnd.google-apps.folder"


def _catalog(db: Session) -> None:
    now = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    for principal in ("ark", "other"):
        db.add(
            GoogleDriveConnection(
                principal_id=principal,
                refresh_token_encrypted="encrypted",
                granted_scopes="https://www.googleapis.com/auth/drive.metadata.readonly",
                root_folder_id="opaque-root-id",
                used_bytes=1_000,
                total_bytes=10_000,
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            GoogleDriveCatalogSync(
                principal_id=principal,
                status="ready",
                catalog_revision=4,
                last_started_at=now,
                last_completed_at=now,
                mode="incremental",
                phase="completed",
                created_at=now,
                updated_at=now,
            )
        )
    values = [
        ("folder", "Projects", FOLDER, None, now - timedelta(days=2), True),
        ("nested", "Archive", FOLDER, None, now - timedelta(days=10), False),
        ("large", "Large.pdf", "application/pdf", 900, now - timedelta(days=5), True),
        ("small", "Small.txt", "text/plain", 10, now - timedelta(days=100), False),
    ]
    for file_id, name, mime, size, modified, starred in values:
        db.add(
            GoogleDriveCatalogItem(
                principal_id="ark",
                drive_file_id=file_id,
                name=name,
                name_search=name.casefold(),
                mime_type=mime,
                size_bytes=size,
                drive_created_at=modified - timedelta(days=1),
                drive_modified_at=modified,
                web_url=f"https://drive.google.com/open?id={file_id}",
                parent_ids=["folder" if file_id in {"nested", "large", "small"} else "root"],
                starred=starred,
                indexed_at=now,
            )
        )
    db.add(
        GoogleDriveCatalogItem(
            principal_id="other",
            drive_file_id="private",
            name="Private.pdf",
            name_search="private.pdf",
            mime_type="application/pdf",
            size_bytes=99_999,
            drive_modified_at=now,
            web_url="https://drive.google.com/open?id=private",
            parent_ids=["root"],
            indexed_at=now,
        )
    )
    db.add_all(
        [
            GoogleDriveParentEdge(
                principal_id="ark",
                child_file_id="folder",
                parent_file_id="root",
            ),
            GoogleDriveParentEdge(
                principal_id="ark", child_file_id="nested", parent_file_id="folder"
            ),
            GoogleDriveParentEdge(
                principal_id="ark", child_file_id="large", parent_file_id="folder"
            ),
            GoogleDriveParentEdge(
                principal_id="ark", child_file_id="small", parent_file_id="folder"
            ),
        ]
    )
    db.commit()


def _login() -> str:
    response = client.post("/auth/login", json={"username": "ark", "password": "test-password"})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_items_filters_sort_and_revision_bound_cursor(db_session: Session) -> None:
    _catalog(db_session)
    _login()

    response = client.get(
        "/integrations/google-drive/items",
        params={"parent_id": "folder", "kind": "document", "sort": "size", "limit": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == ["large"]
    assert payload["items"][0]["kind"] == "document"
    assert payload["items"][0]["parent"] == {
        "id": "folder",
        "name": "Projects",
        "available": True,
    }
    root_items = client.get(
        "/integrations/google-drive/items", params={"parent_id": "root", "kind": "folder"}
    )
    assert root_items.status_code == 200
    assert [item["id"] for item in root_items.json()["items"]] == ["folder"]
    assert root_items.json()["items"][0]["parent"]["id"] == "root"
    cursor = payload["next_cursor"]
    assert cursor
    assert (
        client.get(
            "/integrations/google-drive/items",
            params={"parent_id": "root", "kind": "document", "cursor": cursor},
        ).status_code
        == 400
    )

    sync = db_session.get(GoogleDriveCatalogSync, "ark")
    assert sync is not None
    sync.catalog_revision += 1
    db_session.commit()
    assert (
        client.get(
            "/integrations/google-drive/items",
            params={
                "parent_id": "folder",
                "kind": "document",
                "sort": "size",
                "limit": 1,
                "cursor": cursor,
            },
        ).status_code
        == 409
    )
    assert (
        client.get("/integrations/google-drive/items", params={"q": "private"}).json()["items"]
        == []
    )


def test_items_detect_revision_change_during_query(monkeypatch, db_session: Session) -> None:
    _catalog(db_session)
    _login()
    original = DriveWorkspace._parent_summaries

    def bump_revision(self, principal_id, items):
        result = original(self, principal_id, items)
        sync = self._db.get(GoogleDriveCatalogSync, principal_id)
        assert sync is not None
        sync.catalog_revision += 1
        self._db.commit()
        return result

    monkeypatch.setattr(DriveWorkspace, "_parent_summaries", bump_revision)

    response = client.get("/integrations/google-drive/items")

    assert response.status_code == 409


def test_folder_breadcrumbs_handle_root_missing_parent_and_cycle(db_session: Session) -> None:
    _catalog(db_session)
    _login()

    root = client.get("/integrations/google-drive/folders/root").json()
    nested = client.get("/integrations/google-drive/folders/nested").json()
    assert root["breadcrumbs"] == [{"id": "root", "name": "My Drive", "available": True}]
    assert [value["id"] for value in nested["breadcrumbs"]] == ["root", "folder", "nested"]
    edge = db_session.get(GoogleDriveParentEdge, ("ark", "folder", "root"))
    assert edge is not None
    db_session.delete(edge)
    db_session.add(
        GoogleDriveParentEdge(
            principal_id="ark", child_file_id="folder", parent_file_id="external-parent"
        )
    )
    db_session.commit()
    unavailable = client.get("/integrations/google-drive/folders/nested").json()
    assert unavailable["breadcrumbs_complete"] is False
    assert unavailable["breadcrumbs"][0] == {
        "id": "external-parent",
        "name": "Unavailable folder",
        "available": False,
    }

    external = db_session.get(GoogleDriveParentEdge, ("ark", "folder", "external-parent"))
    assert external is not None
    db_session.delete(external)
    db_session.add(
        GoogleDriveParentEdge(principal_id="ark", child_file_id="folder", parent_file_id="nested")
    )
    db_session.commit()
    cycled = client.get("/integrations/google-drive/folders/nested").json()
    assert cycled["breadcrumbs_complete"] is False


def test_saved_searches_and_pins_require_csrf_and_are_ownership_safe(
    db_session: Session,
) -> None:
    _catalog(db_session)
    csrf = _login()
    saved_payload = {"name": "Starred docs", "kind": "document", "starred": True}

    assert (
        client.post("/integrations/google-drive/saved-searches", json=saved_payload).status_code
        == 403
    )
    created = client.post(
        "/integrations/google-drive/saved-searches",
        json=saved_payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    assert created.json()["filters"]["ownership"] == "owned_by_me"
    assert (
        client.post(
            "/integrations/google-drive/saved-searches",
            json={"name": "Naive date", "modified_after": "2026-01-01T00:00:00"},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 422
    )

    foreign = GoogleDrivePinnedLocation(
        id="foreign-pin",
        principal_id="other",
        drive_folder_id="private",
        created_at=datetime.now(UTC),
    )
    db_session.add(foreign)
    db_session.commit()
    assert (
        client.delete(
            "/integrations/google-drive/pinned-locations/foreign-pin",
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 404
    )
    pin = client.post(
        "/integrations/google-drive/pinned-locations",
        json={"drive_folder_id": "folder", "label": "Work"},
        headers={"X-CSRF-Token": csrf},
    )
    assert pin.status_code == 201
    db_session.delete(db_session.get(GoogleDriveCatalogItem, ("ark", "folder")))
    db_session.commit()
    pins = client.get("/integrations/google-drive/pinned-locations").json()["items"]
    assert pins[0]["available"] is False


def test_insights_sync_history_and_activity_are_normalized(db_session: Session) -> None:
    _catalog(db_session)
    _login()
    now = datetime.now(UTC)
    db_session.add(
        GoogleDriveSyncAttempt(
            id="attempt",
            principal_id="ark",
            mode="incremental",
            status="success",
            phase="completed",
            processed_count=2,
            total_count=2,
            started_at=now,
            completed_at=now,
        )
    )
    db_session.add(
        GoogleDriveActivity(
            id="activity-2",
            principal_id="ark",
            event_type="modified",
            drive_file_id="large",
            name="Large.pdf",
            kind="document",
            summary="Modified metadata observed for Large.pdf.",
            observed_at=now,
        )
    )
    db_session.add(
        GoogleDriveActivity(
            id="activity-1",
            principal_id="ark",
            event_type="created",
            drive_file_id="small",
            name="Small.txt",
            kind="document",
            summary="Created metadata observed for Small.txt.",
            observed_at=now - timedelta(minutes=1),
        )
    )
    db_session.commit()

    insights = client.get("/integrations/google-drive/insights").json()
    assert insights["account_used_bytes"] == 1_000
    assert insights["catalog_known_size_bytes"] == 910
    assert insights["catalog_unknown_size_count"] == 2
    assert insights["largest_files"][0]["id"] == "large"
    assert (
        client.get("/integrations/google-drive/catalog/syncs").json()["items"][0]["id"] == "attempt"
    )
    first_activity = client.get("/integrations/google-drive/activity", params={"limit": 1}).json()
    assert first_activity["scope"] == "sync_observed"
    assert first_activity["items"][0]["id"] == "activity-2"
    assert first_activity["next_cursor"]

    db_session.add(
        GoogleDriveActivity(
            id="newer-activity",
            principal_id="ark",
            event_type="sync_completed",
            summary="A newer synchronization completed.",
            observed_at=now + timedelta(minutes=1),
        )
    )
    db_session.commit()
    second_activity = client.get(
        "/integrations/google-drive/activity",
        params={"limit": 1, "cursor": first_activity["next_cursor"]},
    ).json()
    assert [item["id"] for item in second_activity["items"]] == ["activity-1"]


def test_items_and_search_reject_offset_naive_datetimes(db_session: Session) -> None:
    _catalog(db_session)
    _login()

    assert (
        client.get(
            "/integrations/google-drive/items",
            params={"modified_after": "2026-01-01T00:00:00"},
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/search",
            params={"q": "large", "modified_before": "2026-12-01T00:00:00"},
        ).status_code
        == 422
    )
