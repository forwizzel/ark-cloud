from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.auth.service import token_hash
from app.core.config import Settings, get_settings
from app.main import app
from app.models import LocalUser, TailscaleControl
from app.services.tailscale_control import TailnetClient, decrypt, now

BASE = "/admin/tailscale"
API_KEY = "tskey-api-regression-secret"
AUTH_KEY = "tskey-auth-regression-secret"
CONTROLLER_TOKEN = "isolated-controller-token"


@pytest.fixture
def configuration(tmp_path, monkeypatch):
    secrets = tmp_path / "secrets"
    controller = tmp_path / "controller"
    secrets.mkdir()
    controller.mkdir()
    settings = Settings(
        database_url="sqlite://",
        environment="test",
        tailscale_api_key=None,
        tailscale_secret_directory=str(secrets),
        tailscale_controller_directory=str(controller),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    # Any request outside the explicitly mocked client operations is a test failure.
    monkeypatch.setattr(
        "app.services.tailscale_control._open_request",
        Mock(side_effect=AssertionError("Unexpected external request")),
    )
    return settings


@pytest.fixture
def upstream(configuration, monkeypatch):
    validate = Mock(return_value=None)
    create = Mock(return_value=(AUTH_KEY, "key-1"))
    revoke = Mock(return_value={})
    monkeypatch.setattr(TailnetClient, "validate", validate)
    monkeypatch.setattr(TailnetClient, "create_auth_key", create)
    monkeypatch.setattr(TailnetClient, "revoke_auth_key", revoke)
    return validate, create, revoke


@pytest.fixture
def client(configuration):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def csrf(client):
    response = client.post("/auth/login", json={"username": "ark", "password": "test-password"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


@pytest.fixture
def controller(db_session):
    db_session.add(TailscaleControl(id=1, token_hash=token_hash(CONTROLLER_TOKEN), snapshot={}))
    db_session.commit()
    return {"Authorization": f"Bearer {CONTROLLER_TOKEN}"}


def connect(client, csrf):
    response = client.post(BASE + "/connect", headers=csrf, json={"api_key": API_KEY})
    assert response.status_code == 200
    return response.json()


def report(client, controller, revision, state="connected", **fields):
    return client.post(
        BASE + "/controller/report",
        headers=controller,
        json={"revision": revision, "state": state, "message": "Managed node status", **fields},
    )


def test_admin_csrf_member_and_independent_controller_auth(
    client, controller, upstream, db_session
):
    assert client.get(BASE).status_code == 401
    assert client.post(BASE + "/enable").status_code == 401
    login = client.post("/auth/login", json={"username": "ark", "password": "test-password"})
    csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
    assert client.get(BASE).status_code == 403
    assert client.get(BASE, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.get(BASE, headers=csrf).status_code == 200
    for action in ("connect", "enable", "disable", "disconnect", "test"):
        assert client.post(BASE + "/" + action, json={"api_key": API_KEY}).status_code == 403
    for headers in (
        {},
        csrf,
        {"Authorization": "Bearer wrong"},
        {"Authorization": CONTROLLER_TOKEN},
    ):
        assert client.get(BASE + "/controller/work", headers=headers).status_code == 401
        assert report(client, headers, 0).status_code == 401
    assert client.get(BASE + "/controller/work", headers=controller).status_code == 200
    assert TestClient(app).get(BASE, headers=controller).status_code == 401
    value = db_session.get(TailscaleControl, 1)
    assert value.token_hash == token_hash(CONTROLLER_TOKEN)
    assert value.token_hash != CONTROLLER_TOKEN
    user = db_session.get(LocalUser, "ark")
    user.role = "member"
    db_session.commit()
    assert client.get(BASE, headers=csrf).status_code == 403
    for action in ("connect", "enable", "disable", "disconnect", "test"):
        assert (
            client.post(BASE + "/" + action, headers=csrf, json={"api_key": API_KEY}).status_code
            == 403
        )
    upstream[0].assert_not_called()
    upstream[1].assert_not_called()


def test_connect_encrypts_credentials_and_never_returns_secrets(
    client, csrf, controller, upstream, db_session, configuration
):
    data = connect(client, csrf)
    assert data["configured"] and data["desired_enabled"]
    assert data["source"] == "ui"
    assert data["integration_state"] == "available"
    upstream[0].assert_called_once_with(None)
    work = client.get(BASE + "/controller/work?needs_auth=true", headers=controller)
    assert work.json()["auth_key"] == AUTH_KEY
    assert work.headers["Cache-Control"] == "no-store"
    db_session.expire_all()
    value = db_session.get(TailscaleControl, 1)
    assert decrypt(configuration, value.api_key_encrypted) == API_KEY
    assert decrypt(configuration, value.auth_key_encrypted) == AUTH_KEY
    assert value.auth_key_id == "key-1"
    persisted = repr(
        {column.name: getattr(value, column.name) for column in value.__table__.columns}
    )
    for secret in (API_KEY, AUTH_KEY, CONTROLLER_TOKEN):
        assert secret not in persisted
    for endpoint, method in (("", "get"), ("/test", "post")):
        response = getattr(client, method)(BASE + endpoint, headers=csrf)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        for secret in (API_KEY, AUTH_KEY, CONTROLLER_TOKEN):
            assert secret not in response.text
    assert list(Path(configuration.tailscale_controller_directory).iterdir()) == []


def test_expired_api_key_updates_inventory_status_without_disabling_serve(
    client, csrf, controller, upstream, db_session
):
    data = connect(client, csrf)
    assert (
        report(
            client,
            controller,
            data["revision"],
            node_id="node-1",
            dns_name="arkcloud.test.ts.net",
            serve_url="https://arkcloud.test.ts.net",
        ).status_code
        == 200
    )
    db_session.expire_all()
    value = db_session.get(TailscaleControl, 1)
    value.integration_checked_at = now() - timedelta(minutes=6)
    db_session.commit()
    upstream[0].side_effect = HTTPError("https://api.tailscale.com", 401, "expired", {}, None)
    response = client.get(BASE, headers=csrf)
    assert response.status_code == 200
    data = response.json()
    assert data["integration_state"] == "unavailable"
    assert data["state"] == "connected" and data["desired_enabled"]
    assert data["serve_url"] == "https://arkcloud.test.ts.net"
    calls = upstream[0].call_count
    assert client.get(BASE, headers=csrf).status_code == 200
    assert upstream[0].call_count == calls


def test_controller_cannot_acknowledge_disabled_for_enabled_revision(
    client, csrf, controller, upstream
):
    data = connect(client, csrf)
    assert report(client, controller, data["revision"], state="disabled").status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"api_key": "secret-invalid-key"},
        {"api_key": "tskey-api-secret with-space"},
        {"api_key": "tskey-api-" + "s" * 4096},
        {"api_key": 12345},
        {"api_key": API_KEY, "unexpected_secret": "do-not-echo"},
        {},
    ],
)
def test_invalid_connect_body_is_generic_and_does_not_echo(client, csrf, upstream, body):
    response = client.post(BASE + "/connect", headers=csrf, json=body)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid Tailscale request. Check the submitted fields."}
    upstream[0].assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        HTTPError("https://api.tailscale.com", 403, API_KEY, {}, None),
        URLError(API_KEY),
        ValueError(API_KEY),
    ],
)
def test_failed_replacement_preserves_working_credentials_and_pending_key(
    client, csrf, controller, upstream, db_session, error
):
    initial = connect(client, csrf)
    client.get(BASE + "/controller/work?needs_auth=true", headers=controller)
    db_session.expire_all()
    value = db_session.get(TailscaleControl, 1)
    before = (value.api_key_encrypted, value.auth_key_encrypted, value.auth_key_id, value.revision)
    upstream[0].side_effect = error
    response = client.post(
        BASE + "/connect", headers=csrf, json={"api_key": "tskey-api-replacement"}
    )
    assert response.status_code == 422
    assert API_KEY not in response.text
    assert "replacement" not in response.text
    expected = (
        "Tailscale rejected this key or its permissions. "
        "Use an API key allowed to register devices."
        if isinstance(error, HTTPError)
        else "Tailscale could not be reached or returned an invalid response. Retry the connection."
    )
    assert response.json()["detail"] == expected
    db_session.expire_all()
    value = db_session.get(TailscaleControl, 1)
    assert (
        value.api_key_encrypted,
        value.auth_key_encrypted,
        value.auth_key_id,
        value.revision,
    ) == before
    assert value.desired_enabled
    assert value.revision == initial["revision"]
    upstream[2].assert_not_called()


def test_existing_node_cannot_be_replaced_with_key_for_another_tailnet(
    client, csrf, db_session, monkeypatch
):
    request = Mock(return_value={"devices": []})
    monkeypatch.setattr(TailnetClient, "request", request)
    initial = connect(client, csrf)
    value = db_session.get(TailscaleControl, 1)
    value.snapshot = {"node_id": "existing-node"}
    db_session.commit()
    response = client.post(
        BASE + "/connect", headers=csrf, json={"api_key": "tskey-api-other-tailnet"}
    )
    assert response.status_code == 409
    db_session.expire_all()
    assert db_session.get(TailscaleControl, 1).revision == initial["revision"]


def test_environment_fallback_is_suppressed_after_disconnect(
    client, csrf, configuration, upstream, db_session
):
    configuration.tailscale_api_key = SecretStr("tskey-api-environment")
    configuration.tailscale_tailnet = "environment.example"
    assert client.get(BASE, headers=csrf).json()["source"] == "environment"
    enabled = client.post(BASE + "/enable", headers=csrf).json()
    assert enabled["desired_enabled"] and enabled["source"] == "ui"
    db_session.expire_all()
    value = db_session.get(TailscaleControl, 1)
    assert decrypt(configuration, value.api_key_encrypted) == "tskey-api-environment"
    assert value.tailnet == "environment.example"
    response = client.post(BASE + "/disconnect", headers=csrf)
    assert response.status_code == 200
    assert response.json()["source"] == "none"
    assert not response.json()["configured"]
    assert not client.get(BASE, headers=csrf).json()["configured"]
    assert client.post(BASE + "/enable", headers=csrf).status_code == 409
    assert client.post(BASE + "/test", headers=csrf).status_code == 409


def test_controller_caches_single_use_key_and_rejects_stale_reports(
    client, csrf, controller, upstream, db_session
):
    initial = connect(client, csrf)
    url = BASE + "/controller/work?needs_auth=true"
    assert client.get(url).status_code == 401
    upstream[1].assert_not_called()
    assert client.get(BASE + "/controller/work", headers=controller).json()["auth_key"] is None
    for _ in range(2):
        assert client.get(url, headers=controller).json()["auth_key"] == AUTH_KEY
    upstream[1].assert_called_once_with()
    assert report(client, controller, initial["revision"] - 1).status_code == 409
    db_session.expire_all()
    assert db_session.get(TailscaleControl, 1).auth_key_id == "key-1"
    assert (
        report(
            client,
            controller,
            initial["revision"],
            node_id="node-1",
            dns_name="ark.tail.ts.net",
            serve_url="https://ark.tail.ts.net",
        ).status_code
        == 200
    )
    assert client.get(BASE + "/controller/work", headers=controller).json()["auth_key"] is None
    db_session.expire_all()
    assert db_session.get(TailscaleControl, 1).auth_key_encrypted is None


def test_expired_pending_key_is_revoked_and_replaced(
    client, csrf, controller, upstream, db_session
):
    connect(client, csrf)
    url = BASE + "/controller/work?needs_auth=true"
    client.get(url, headers=controller)
    db_session.expire_all()
    value = db_session.get(TailscaleControl, 1)
    value.auth_key_expires_at = now() - timedelta(seconds=1)
    db_session.commit()
    upstream[1].return_value = ("tskey-auth-fresh", "key-2")
    assert client.get(url, headers=controller).json()["auth_key"] == "tskey-auth-fresh"
    upstream[2].assert_called_once_with("key-1")
    assert upstream[1].call_count == 2


def test_enable_disable_disconnect_and_approval_transitions(client, csrf, controller, upstream):
    initial = connect(client, csrf)
    revision = initial["revision"]
    approval = "https://login.tailscale.com/a/device-1"
    assert (
        report(
            client,
            controller,
            revision,
            "approval_required",
            node_id="node-1",
            approval_url=approval,
        ).status_code
        == 200
    )
    status = client.get(BASE, headers=csrf).json()
    assert status["state"] == "approval_required"
    assert status["approval_url"] == approval
    assert status["serve_url"] is None
    fields = {
        "node_id": "node-1",
        "dns_name": "ark.tail.ts.net",
        "serve_url": "https://ark.tail.ts.net",
    }
    assert report(client, controller, revision, **fields).status_code == 200
    assert client.get(BASE, headers=csrf).json()["serve_url"] == fields["serve_url"]
    disabled = client.post(BASE + "/disable", headers=csrf).json()
    assert disabled["revision"] == revision + 1
    assert disabled["state"] == "connecting"
    assert disabled["serve_url"] is None
    assert not disabled["desired_enabled"]
    assert report(client, controller, disabled["revision"], **fields).status_code == 409
    assert report(client, controller, disabled["revision"], "disconnected").status_code == 409
    assert report(client, controller, disabled["revision"], "disabled").status_code == 200
    assert client.get(BASE, headers=csrf).json()["state"] == "disabled"
    enabled = client.post(BASE + "/enable", headers=csrf).json()
    assert enabled["desired_enabled"] and enabled["revision"] == revision + 2
    assert report(client, controller, enabled["revision"], **fields).status_code == 200
    client.get(BASE + "/controller/work?needs_auth=true", headers=controller)
    disconnected = client.post(BASE + "/disconnect", headers=csrf).json()
    upstream[2].assert_called_once_with("key-1")
    work = client.get(BASE + "/controller/work?needs_auth=true", headers=controller).json()
    assert work["disconnect"] and not work["desired_enabled"]
    assert work["auth_key"] is None
    assert report(client, controller, disconnected["revision"], "disconnected").status_code == 200
    assert client.get(BASE, headers=csrf).json()["state"] == "disconnected"


@pytest.mark.parametrize(
    "fields",
    [
        {"dns_name": "evil.example", "serve_url": "https://evil.example"},
        {"dns_name": "ark.tail.ts.net", "serve_url": "https://ark.tail.ts.net.evil.example"},
        {"dns_name": "ark.tail.ts.net", "serve_url": "https://ark.tail.ts.net/path"},
        {"dns_name": "ARK.tail.ts.net"},
        {"approval_url": "http://login.tailscale.com/a/device"},
        {"approval_url": "https://login.tailscale.com.evil.example/a/device"},
        {"approval_url": "https://login.tailscale.com@evil.example/a/device"},
        {"approval_url": "https://login.tailscale.com/a/device#secret"},
        {"approval_url": "https://login.tailscale.com/redirect"},
        {"approval_url": "https://console.tailscale.com:443/admin/devices"},
    ],
)
def test_controller_rejects_malicious_or_noncanonical_urls(
    client, csrf, controller, upstream, fields
):
    revision = connect(client, csrf)["revision"]
    assert report(client, controller, revision, "approval_required", **fields).status_code == 422
    status = client.get(BASE, headers=csrf).json()
    assert status["serve_url"] is None and status["approval_url"] is None


def test_stale_controller_cannot_advertise_private_access(
    client, csrf, controller, upstream, db_session
):
    revision = connect(client, csrf)["revision"]
    assert (
        report(
            client,
            controller,
            revision,
            node_id="node-1",
            dns_name="ark.tail.ts.net",
            serve_url="https://ark.tail.ts.net",
        ).status_code
        == 200
    )
    value = db_session.get(TailscaleControl, 1)
    value.last_seen_at = now() - timedelta(seconds=46)
    db_session.commit()
    status = client.get(BASE, headers=csrf).json()
    assert status["state"] == "offline"
    assert not status["controller_online"]
    assert status["serve_url"] is None


@pytest.mark.parametrize("change", ["demoted", "inactive", "deleted"])
def test_requesting_admin_losing_access_cancels_pending_work(
    client, csrf, controller, upstream, db_session, change
):
    revision = connect(client, csrf)["revision"]
    client.get(BASE + "/controller/work?needs_auth=true", headers=controller)
    user = db_session.get(LocalUser, "ark")
    if change == "demoted":
        user.role = "member"
    elif change == "inactive":
        user.active = False
    else:
        db_session.delete(user)
    db_session.commit()
    work = client.get(BASE + "/controller/work?needs_auth=true", headers=controller).json()
    assert not work["desired_enabled"] and work["auth_key"] is None
    assert work["revision"] == revision + 1
    upstream[2].assert_called_once_with("key-1")
    assert upstream[1].call_count == 1
    assert (
        report(
            client,
            controller,
            revision,
            node_id="node-1",
            dns_name="ark.tail.ts.net",
            serve_url="https://ark.tail.ts.net",
        ).status_code
        == 409
    )
    assert (
        client.get(BASE + "/controller/work", headers=controller).json()["revision"]
        == work["revision"]
    )
    db_session.expire_all()
    value = db_session.get(TailscaleControl, 1)
    assert value.principal_id is None and value.auth_key_encrypted is None
    assert value.snapshot["state"] == "error"


def test_upstream_key_creation_failure_is_normalized(client, csrf, controller, upstream):
    connect(client, csrf)
    upstream[1].side_effect = URLError(AUTH_KEY)
    response = client.get(BASE + "/controller/work?needs_auth=true", headers=controller)
    assert response.status_code == 503
    assert AUTH_KEY not in response.text
    status = client.get(BASE, headers=csrf).json()
    assert status["integration_state"] == "unavailable"
    assert status["state"] == "error"
    assert status["serve_url"] is None


def test_connection_test_failure_preserves_credentials_and_recovers(
    client, csrf, upstream, db_session
):
    initial = connect(client, csrf)
    db_session.expire_all()
    encrypted = db_session.get(TailscaleControl, 1).api_key_encrypted
    upstream[0].side_effect = HTTPError("https://api.tailscale.com", 401, API_KEY, {}, None)
    response = client.post(BASE + "/test", headers=csrf)
    assert response.status_code == 200
    assert response.json()["integration_state"] == "unavailable"
    assert response.json()["configured"]
    assert response.json()["revision"] == initial["revision"]
    assert "Tailscale rejected this key" in response.json()["integration_message"]
    assert API_KEY not in response.text
    db_session.expire_all()
    assert db_session.get(TailscaleControl, 1).api_key_encrypted == encrypted
    upstream[0].side_effect = None
    assert client.post(BASE + "/test", headers=csrf).json()["integration_state"] == "available"


def test_disable_clears_pending_key_even_when_revocation_is_unavailable(
    client, csrf, controller, upstream, db_session
):
    initial = connect(client, csrf)
    client.get(BASE + "/controller/work?needs_auth=true", headers=controller)
    upstream[2].side_effect = URLError(AUTH_KEY)
    response = client.post(BASE + "/disable", headers=csrf)
    assert response.status_code == 200
    assert not response.json()["desired_enabled"]
    assert response.json()["configured"]
    assert response.json()["revision"] == initial["revision"] + 1
    assert AUTH_KEY not in response.text
    db_session.expire_all()
    value = db_session.get(TailscaleControl, 1)
    assert value.auth_key_encrypted is None
    assert value.auth_key_id is None
    assert value.auth_key_expires_at is None
    assert (
        client.get(BASE + "/controller/work?needs_auth=true", headers=controller).json()["auth_key"]
        is None
    )
    upstream[1].assert_called_once_with()


def test_connect_normalizes_surrounding_whitespace(
    client, csrf, upstream, db_session, configuration
):
    response = client.post(BASE + "/connect", headers=csrf, json={"api_key": "  " + API_KEY + "\n"})
    assert response.status_code == 200
    db_session.expire_all()
    assert decrypt(configuration, db_session.get(TailscaleControl, 1).api_key_encrypted) == API_KEY


@pytest.mark.parametrize(
    "approval",
    ["https://console.tailscale.com/admin/devices", "https://login.tailscale.com/f/device-1"],
)
def test_controller_accepts_only_approved_tailscale_approval_addresses(
    client, csrf, controller, upstream, approval
):
    revision = connect(client, csrf)["revision"]
    response = report(client, controller, revision, "approval_required", approval_url=approval)
    assert response.status_code == 200
    assert client.get(BASE, headers=csrf).json()["approval_url"] == approval
