from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.service import now, token_hash
from app.main import app
from app.models import AuthSession, BootstrapCode, LocalUser


def sign_in(client: TestClient, username: str = "ark", password: str = "test-password") -> str:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_fresh_setup_requires_code_and_can_only_create_one_admin(db_session: Session) -> None:
    db_session.execute(delete(LocalUser))
    db_session.add(
        BootstrapCode(
            id=1,
            token_hash=token_hash("example-setup-token-long-enough"),
            expires_at=now() + timedelta(minutes=15),
        )
    )
    db_session.commit()
    first = TestClient(app)
    second = TestClient(app)
    assert first.get("/auth/session").json()["setup_required"] is True
    invalid = first.post(
        "/auth/setup",
        json={
            "code": "incorrect-setup-token-long-enough",
            "username": "first",
            "password": "long test password",
        },
    )
    assert invalid.status_code == 403
    created = first.post(
        "/auth/setup",
        json={
            "code": "example-setup-token-long-enough",
            "username": "First",
            "password": "long test password",
        },
    )
    assert created.status_code == 200
    assert created.json()["username"] == "first"
    assert created.json()["role"] == "admin"
    assert second.get("/auth/session").json()["setup_required"] is False
    assert (
        second.post(
            "/auth/setup",
            json={
                "code": "example-setup-token-long-enough",
                "username": "another",
                "password": "long test password",
            },
        ).status_code
        == 409
    )
    assert (
        db_session.scalar(select(LocalUser).where(LocalUser.username == "first")).password_hash
        != "long test password"
    )


def test_username_password_and_session_revocation_preserve_account_identity(
    db_session: Session,
) -> None:
    client = TestClient(app)
    other_device = TestClient(app)
    csrf = sign_in(client)
    sign_in(other_device)
    old_hash = db_session.get(LocalUser, "ark").password_hash
    changed = client.put(
        "/auth/account/username",
        headers={"X-CSRF-Token": csrf},
        json={"username": "My.Name", "current_password": "test-password"},
    )
    assert changed.status_code == 200
    assert changed.json()["username"] == "my.name"
    db_session.expire_all()
    assert db_session.get(LocalUser, "ark").username == "my.name"
    assert db_session.get(LocalUser, "ark").password_hash == old_hash
    assert other_device.get("/auth/session").json()["username"] == "my.name"
    assert (
        client.put(
            "/auth/account/password",
            json={"current_password": "test-password", "new_password": "new long password"},
        ).status_code
        == 403
    )
    changed = client.put(
        "/auth/account/password",
        headers={"X-CSRF-Token": csrf},
        json={"current_password": "test-password", "new_password": "new long password"},
    )
    assert changed.status_code == 204
    assert client.get("/auth/session").json()["authenticated"] is False
    assert other_device.get("/auth/session").json()["authenticated"] is False
    assert (
        client.post(
            "/auth/login", json={"username": "my.name", "password": "test-password"}
        ).status_code
        == 401
    )
    sign_in(client, "my.name", "new long password")


def test_admin_invitation_is_one_use_and_member_is_restricted(db_session: Session) -> None:
    admin = TestClient(app)
    member = TestClient(app)
    csrf = sign_in(admin)
    denied = admin.post("/auth/users", json={"username": "someone", "role": "member"})
    assert denied.status_code == 403
    invited = admin.post(
        "/auth/users",
        headers={"X-CSRF-Token": csrf},
        json={"username": "someone", "role": "member"},
    )
    assert invited.status_code == 201
    token = invited.json()["token"]
    assert "password_hash" not in str(admin.get("/auth/users").json())
    assert (
        member.post("/auth/invite/redeem", json={"token": token, "password": "small"}).status_code
        == 422
    )
    redeemed = member.post(
        "/auth/invite/redeem", json={"token": token, "password": "member password long"}
    )
    assert redeemed.status_code == 200
    assert (
        member.post(
            "/auth/invite/redeem", json={"token": token, "password": "member password long"}
        ).status_code
        == 403
    )
    assert member.get("/auth/users").status_code == 403
    assert (
        member.post(
            "/auth/users",
            headers={"X-CSRF-Token": redeemed.json()["csrf_token"]},
            json={"username": "intruder", "role": "admin"},
        ).status_code
        == 403
    )
    assert member.get("/storage/roots").status_code == 200
    user = db_session.scalar(select(LocalUser).where(LocalUser.username == "someone"))
    assert user.id != "ark"
    assert (
        admin.patch(
            f"/auth/users/{user.id}", headers={"X-CSRF-Token": csrf}, json={"active": False}
        ).status_code
        == 200
    )
    assert member.get("/auth/session").json()["authenticated"] is False
    assert (
        admin.patch(
            "/auth/users/ark", headers={"X-CSRF-Token": csrf}, json={"active": False}
        ).status_code
        == 409
    )


def test_old_sessions_do_not_authenticate_without_active_user(db_session: Session) -> None:
    client = TestClient(app)
    sign_in(client)
    assert db_session.scalar(select(AuthSession)) is not None
    user = db_session.get(LocalUser, "ark")
    user.active = False
    db_session.commit()
    assert client.get("/auth/session").json()["authenticated"] is False


def test_pending_admin_cannot_replace_last_signed_in_admin() -> None:
    client = TestClient(app)
    csrf = sign_in(client)
    response = client.post(
        "/auth/users",
        headers={"X-CSRF-Token": csrf},
        json={"username": "pending.admin", "role": "admin"},
    )
    assert response.status_code == 201
    assert (
        client.patch(
            "/auth/users/ark", headers={"X-CSRF-Token": csrf}, json={"active": False}
        ).status_code
        == 409
    )


def test_login_throttling_and_same_origin_guard() -> None:
    client = TestClient(app)
    assert (
        client.post(
            "/auth/login",
            json={"username": "ark", "password": "wrong"},
            headers={"Sec-Fetch-Site": "cross-site"},
        ).status_code
        == 403
    )
    for _ in range(8):
        assert (
            client.post("/auth/login", json={"username": "ark", "password": "wrong"}).status_code
            == 401
        )
    assert (
        client.post(
            "/auth/login", json={"username": "ark", "password": "test-password"}
        ).status_code
        == 429
    )
