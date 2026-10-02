import json
import stat
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.service import token_hash
from app.core.config import Settings
from app.core.database import SessionLocal
from app.main import app
from app.services import tailscale_control as service


@pytest.fixture
def configuration(tmp_path):
    secrets = tmp_path / "secrets"
    controller = tmp_path / "controller"
    secrets.mkdir()
    controller.mkdir()
    return Settings(
        database_url="sqlite://",
        environment="test",
        tailscale_api_key="tskey-api-environment",
        tailscale_tailnet="environment.example",
        tailscale_secret_directory=str(secrets),
        tailscale_controller_directory=str(controller),
    )


class Response:
    def __init__(self, body):
        self.body = body
        self.limits = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, limit):
        self.limits.append(limit)
        return self.body[:limit]


def test_test_environment_initialization_has_no_side_effects(
    configuration, db_session, monkeypatch
):
    session = Mock(side_effect=AssertionError("Test initialization must not use database"))
    monkeypatch.setattr(service, "SessionLocal", session)
    service.initialize(configuration)
    assert list(Path(configuration.tailscale_secret_directory).iterdir()) == []
    assert list(Path(configuration.tailscale_controller_directory).iterdir()) == []
    assert db_session.get(service.TailscaleControl, 1) is None


def test_lifespan_initializes_separate_secret_volumes_and_hash_only_token(
    configuration, db_session, monkeypatch
):
    settings = configuration.model_copy(update={"environment": "development"})
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr(service, "SessionLocal", SessionLocal)
    secrets = Path(settings.tailscale_secret_directory)
    controller = Path(settings.tailscale_controller_directory)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        key_file = secrets / "encryption-key"
        token_file = controller / "controller-token"
        key, token = key_file.read_bytes(), token_file.read_text()
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(token_file.stat().st_mode) == 0o640
        assert {p.name for p in secrets.iterdir()} == {"encryption-key"}
        assert {p.name for p in controller.iterdir()} == {"controller-token"}
        db_session.expire_all()
        value = db_session.get(service.TailscaleControl, 1)
        assert value.token_hash == token_hash(token)
        assert value.token_hash != token
        assert (
            client.get(
                "/admin/tailscale/controller/work", headers={"Authorization": "Bearer " + token}
            ).status_code
            == 200
        )
    with TestClient(app):
        assert key_file.read_bytes() == key
        assert token_file.read_text() == token
    db_session.expire_all()
    assert db_session.get(service.TailscaleControl, 1).token_hash == token_hash(token)


def test_credentials_are_encrypted_and_require_original_secret_volume(configuration, tmp_path):
    secret = "tskey-api-private"
    encrypted = service.encrypt(configuration, secret)
    assert secret not in encrypted
    assert service.decrypt(configuration, encrypted) == secret
    other = tmp_path / "other-volume"
    other.mkdir()
    wrong_settings = configuration.model_copy(update={"tailscale_secret_directory": str(other)})
    with pytest.raises(HTTPException) as error:
        service.decrypt(wrong_settings, encrypted)
    assert error.value.status_code == 503
    assert secret not in error.value.detail


def test_runtime_integration_uses_saved_credentials_and_disconnect_suppresses_environment(
    configuration, db_session
):
    assert service.credentials(None, configuration) == (
        "tskey-api-environment",
        "environment.example",
        "environment",
    )
    value = service.control(db_session)
    value.configured_override = True
    value.api_key_encrypted = service.encrypt(configuration, "tskey-api-saved")
    value.tailnet = "saved.example"
    db_session.commit()
    integration = service.runtime_integration(db_session, configuration)
    requests = []

    def opener(request, timeout):
        requests.append(request)
        assert timeout == 5
        return Response(b'{"devices": []}')

    integration._opener = opener
    assert integration.summary().state == "healthy"
    assert requests[0].get_header("Authorization") == "Bearer tskey-api-saved"
    assert requests[0].full_url == "https://api.tailscale.com/api/v2/tailnet/saved.example/devices"
    value.api_key_encrypted = None
    db_session.commit()
    assert service.credentials(value, configuration) == (None, "saved.example", "none")
    assert (
        service.runtime_integration(db_session, configuration).summary().state == "not_configured"
    )


def test_missing_encryption_key_is_a_partial_integration_failure(configuration, db_session):
    value = service.control(db_session)
    value.configured_override = True
    value.api_key_encrypted = "unreadable-ciphertext"
    db_session.commit()
    summary = service.runtime_integration(db_session, configuration).summary()
    assert summary.state == "unavailable"
    assert "secret volume" in summary.message
    assert "unreadable-ciphertext" not in summary.message


@pytest.mark.parametrize("trusted", [False, True])
def test_remote_login_requires_gateway_proof_for_secure_cookies(db_session, trusted):
    value = service.control(db_session)
    value.token_hash = token_hash("gateway-proof")
    db_session.commit()
    client = TestClient(app, base_url="https://arkcloud.example.ts.net")
    headers = {"X-Forwarded-Proto": "https"}
    if trusted:
        headers["X-Ark-Remote-Access"] = "gateway-proof"
    else:
        headers["X-Ark-Remote-Access"] = "client-spoof"
    response = client.post(
        "/auth/login",
        json={"username": "ark", "password": "test-password"},
        headers=headers,
    )
    assert response.status_code == 200
    assert all(
        ("Secure" in cookie) is trusted for cookie in response.headers.get_list("set-cookie")
    )


def test_tailnet_requests_use_fixed_origin_encoded_path_and_bearer_auth(monkeypatch):
    captured = []

    def opener(request, timeout):
        captured.append(request)
        assert timeout == 5
        return Response(b"{}")

    monkeypatch.setattr(service, "_open_request", opener)
    client = service.TailnetClient("tskey-api-private", "https://evil.example/tailnet?secret")
    client.request("devices")
    request = captured[0]
    assert (
        request.full_url
        == "https://api.tailscale.com/api/v2/tailnet/https%3A%2F%2Fevil.example%2Ftailnet%3Fsecret/devices"
    )
    assert request.get_header("Authorization") == "Bearer tskey-api-private"
    assert request.get_header("Accept") == "application/json"
    assert request.get_method() == "GET"
    client.revoke_auth_key("key/with?query")
    assert captured[1].get_method() == "DELETE"
    assert captured[1].full_url.endswith("/keys/key%2Fwith%3Fquery")


def test_tailnet_client_shared_opener_refuses_redirects(monkeypatch):
    from app.integrations import tailscale

    request = None

    def build_opener(handler):
        assert isinstance(handler, tailscale._NoRedirectHandler)
        assert (
            handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example") is None
        )

        def open_request(value, timeout):
            nonlocal request
            request = value
            assert timeout == 5
            raise HTTPError(
                value.full_url, 302, "Found", {"Location": "https://evil.example"}, None
            )

        return Mock(open=open_request)

    monkeypatch.setattr(tailscale, "build_opener", build_opener)
    with pytest.raises(HTTPError) as error:
        service.TailnetClient("private-key").request("devices")
    assert error.value.code == 302
    assert request.full_url.startswith("https://api.tailscale.com/")


@pytest.mark.parametrize("body", [b"not-json", b"[]", b"null", b'"secret"', b"x" * 2_000_001])
def test_tailnet_client_rejects_invalid_and_oversized_response(monkeypatch, body):
    response = Response(body)
    monkeypatch.setattr(service, "_open_request", lambda *_args, **_kwargs: response)
    with pytest.raises(ValueError):
        service.TailnetClient("private-key").request("devices")
    assert response.limits == [2_000_001]


def test_single_use_auth_key_capabilities_and_response(monkeypatch):
    captured = []

    def opener(request, timeout):
        captured.append(request)
        return Response(
            b'{"key": "tskey-auth-private", "id": "key_123", "raw_secret": "not-returned"}'
        )

    monkeypatch.setattr(service, "_open_request", opener)
    assert service.TailnetClient("private-key").create_auth_key() == (
        "tskey-auth-private",
        "key_123",
    )
    request = captured[0]
    assert request.get_method() == "POST"
    assert request.full_url == "https://api.tailscale.com/api/v2/tailnet/-/keys"
    body = json.loads(request.data)
    assert body["capabilities"] == {
        "devices": {"create": {"reusable": False, "ephemeral": False, "preauthorized": True}}
    }
    assert body["expirySeconds"] == 86400


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"key": "wrong-prefix", "id": "valid"},
        {"key": "tskey-auth-with space", "id": "valid"},
        {"key": "tskey-auth-" + "x" * 4096, "id": "valid"},
        {"key": 123, "id": "valid"},
        {"key": "tskey-auth-valid", "id": "../other"},
        {"key": "tskey-auth-valid", "id": "x" * 129},
        {"key": "tskey-auth-valid", "id": None},
    ],
)
def test_auth_key_rejects_invalid_upstream_secrets_or_ids(monkeypatch, payload):
    monkeypatch.setattr(
        service, "_open_request", lambda *_args, **_kwargs: Response(json.dumps(payload).encode())
    )
    with pytest.raises(ValueError):
        service.TailnetClient("private-key").create_auth_key()


@pytest.mark.parametrize("devices", [None, {}, ["invalid-device"]])
def test_validate_rejects_invalid_device_inventory(monkeypatch, devices):
    monkeypatch.setattr(
        service,
        "_open_request",
        lambda *_args, **_kwargs: Response(json.dumps({"devices": devices}).encode()),
    )
    with pytest.raises(ValueError):
        service.TailnetClient("private-key").validate()


@pytest.mark.parametrize("device", [{"id": 123}, {"nodeId": "123"}])
def test_validate_checks_existing_node_membership(monkeypatch, device):
    monkeypatch.setattr(
        service,
        "_open_request",
        lambda *_args, **_kwargs: Response(json.dumps({"devices": [device]}).encode()),
    )
    client = service.TailnetClient("private-key")
    client.validate("123")
    with pytest.raises(HTTPException) as error:
        client.validate("different-node")
    assert error.value.status_code == 409
    assert "private-key" not in error.value.detail
