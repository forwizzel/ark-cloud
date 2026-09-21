from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import GoogleDriveCatalogItem, GoogleDriveCatalogSync, GoogleDriveConnection

client = TestClient(app)


def add_catalog(db: Session) -> None:
    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    for principal in ("ark", "someone-else"):
        db.add(
            GoogleDriveConnection(
                principal_id=principal,
                refresh_token_encrypted="encrypted",
                granted_scopes="https://www.googleapis.com/auth/drive.metadata.readonly",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            GoogleDriveCatalogSync(
                principal_id=principal,
                status="ready",
                last_started_at=now,
                last_completed_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    db.add_all(
        [
            GoogleDriveCatalogItem(
                principal_id="ark",
                drive_file_id="newer",
                name="Tax Return 2026.pdf",
                name_search="tax return 2026.pdf",
                mime_type="application/pdf",
                size_bytes=200,
                drive_modified_at=datetime(2026, 2, 1, tzinfo=UTC),
                web_url="https://drive.google.com/open?id=newer",
                parent_ids=["root"],
                indexed_at=now,
            ),
            GoogleDriveCatalogItem(
                principal_id="ark",
                drive_file_id="older",
                name="Tax Return 2025.pdf",
                name_search="tax return 2025.pdf",
                mime_type="application/pdf",
                size_bytes=100,
                drive_modified_at=datetime(2025, 2, 1, tzinfo=UTC),
                web_url="https://drive.google.com/open?id=older",
                parent_ids=["root"],
                indexed_at=now,
            ),
            GoogleDriveCatalogItem(
                principal_id="someone-else",
                drive_file_id="private",
                name="Private Tax Return.pdf",
                name_search="private tax return.pdf",
                mime_type="application/pdf",
                size_bytes=300,
                drive_modified_at=datetime(2026, 3, 1, tzinfo=UTC),
                web_url="https://drive.google.com/open?id=private",
                parent_ids=["root"],
                indexed_at=now,
            ),
        ]
    )
    db.commit()


def login() -> None:
    response = client.post("/auth/login", json={"username": "ark", "password": "test-password"})
    assert response.status_code == 200


def test_search_is_principal_scoped_and_cursor_paginated(db_session: Session) -> None:
    add_catalog(db_session)
    login()

    first = client.get("/search", params={"q": "tax return", "limit": 1})
    assert first.status_code == 200
    first_payload = first.json()
    assert [item["id"] for item in first_payload["items"]] == ["newer"]
    assert first_payload["next_cursor"]
    assert first_payload["catalog"]["item_count"] == 2

    second = client.get(
        "/search",
        params={"q": "tax return", "limit": 1, "cursor": first_payload["next_cursor"]},
    )
    assert second.status_code == 200
    assert [item["id"] for item in second.json()["items"]] == ["older"]
    assert second.json()["next_cursor"] is None
    private = client.get("/search", params={"q": "private"})
    assert private.status_code == 200
    assert private.json()["items"] == []


def test_search_rejects_blank_queries_and_invalid_cursors(db_session: Session) -> None:
    add_catalog(db_session)
    login()

    assert client.get("/search", params={"q": "   "}).status_code == 422
    assert client.get("/search", params={"q": "tax", "cursor": "invalid"}).status_code == 400


def test_search_requires_authentication() -> None:
    client.cookies.clear()

    assert client.get("/search", params={"q": "tax"}).status_code == 401
