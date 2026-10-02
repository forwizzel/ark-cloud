"""Runtime credentials and desired state, isolated from the managed node."""

import json
import os
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.service import token_hash
from app.core.config import Settings
from app.core.database import SessionLocal
from app.integrations.tailscale import TAILSCALE_API_ORIGIN, TailscaleIntegration, _open_request
from app.models import TailscaleControl


def now():
    return datetime.now(UTC)


def control(db: Session) -> TailscaleControl:
    if db.bind.dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(734020)))
    value = db.get(TailscaleControl, 1, populate_existing=True)
    if value is None:
        value = TailscaleControl(id=1, snapshot={})
        db.add(value)
        db.flush()
    return value


def secret_file(directory: str, name: str, generate, mode=0o600) -> bytes:
    path = Path(directory) / name
    # Directories are provisioned by Compose, never arbitrary host mounts.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    except FileExistsError:
        return path.read_bytes().strip()
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), mode)
        value = generate()
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    return value


def cipher(settings: Settings) -> Fernet:
    return Fernet(
        secret_file(settings.tailscale_secret_directory, "encryption-key", Fernet.generate_key)
    )


def encrypt(settings: Settings, value: str) -> str:
    return cipher(settings).encrypt(value.encode()).decode()


def decrypt(settings: Settings, value: str) -> str:
    try:
        return cipher(settings).decrypt(value.encode()).decode()
    except InvalidToken, OSError, ValueError:
        raise HTTPException(
            503, "Tailscale credentials could not be unlocked. Restore the secret volume."
        ) from None


def initialize(settings: Settings):
    # Unit tests do not need filesystem secrets or a controller.
    if settings.environment == "test":
        return
    cipher(settings)
    token = secret_file(
        settings.tailscale_controller_directory,
        "controller-token",
        lambda: secrets.token_urlsafe(48).encode(),
        0o640,
    ).decode()
    with SessionLocal() as db:
        value = control(db)
        value.token_hash = token_hash(token)
        db.commit()


def credentials(value: TailscaleControl | None, settings: Settings):
    if value and value.configured_override:
        return (
            decrypt(settings, value.api_key_encrypted) if value.api_key_encrypted else None,
            value.tailnet,
            "ui" if value.api_key_encrypted else "none",
        )
    key = settings.tailscale_api_key
    return (
        key.get_secret_value() if key else None,
        settings.tailscale_tailnet,
        "environment" if key and key.get_secret_value() else "none",
    )


def runtime_integration(db: Session, settings: Settings):
    try:
        key, tailnet, _ = credentials(db.get(TailscaleControl, 1), settings)
    except HTTPException:
        return TailscaleIntegration(
            settings,
            configuration_error=(
                "Saved Tailscale credentials are unavailable. Restore the secret volume."
            ),
        )
    resolved = settings.model_copy(
        update={"tailscale_api_key": SecretStr(key) if key else None, "tailscale_tailnet": tailnet}
    )
    return TailscaleIntegration(resolved)


class TailnetClient:
    def __init__(self, key: str, tailnet: str = "-"):
        self.key = key
        self.tailnet = tailnet

    def request(self, suffix: str, method="GET", body=None):
        request = Request(
            f"{TAILSCALE_API_ORIGIN}/api/v2/tailnet/{quote(self.tailnet, safe='')}/{suffix}",
            method=method,
            headers={
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            data=json.dumps(body).encode() if body is not None else None,
        )
        with _open_request(request, timeout=5) as response:
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError()
        result = json.loads(data) if data else {}
        if not isinstance(result, dict):
            raise ValueError()
        return result

    def validate(self, node_id=None):
        devices = self.request("devices").get("devices")
        if not isinstance(devices, list) or not all(isinstance(device, dict) for device in devices):
            raise ValueError()
        if node_id and not any(node_id in (str(d.get("id", "")), d.get("nodeId")) for d in devices):
            raise HTTPException(
                409,
                "This key cannot access ArkCloud's existing Tailscale node. "
                "Disconnect before changing tailnets.",
            )

    def create_auth_key(self):
        result = self.request(
            "keys",
            "POST",
            {
                "capabilities": {
                    "devices": {
                        "create": {"reusable": False, "ephemeral": False, "preauthorized": True}
                    }
                },
                "expirySeconds": 86400,
                "description": "ArkCloud managed node",
            },
        )
        key, key_id = result.get("key"), result.get("id")
        if (
            not isinstance(key, str)
            or not key.startswith("tskey-auth-")
            or len(key) > 4096
            or any(c.isspace() for c in key)
        ):
            raise ValueError()
        if not isinstance(key_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", key_id):
            raise ValueError()
        return key, key_id

    def revoke_auth_key(self, key_id):
        return self.request(f"keys/{quote(key_id, safe='')}", "DELETE")
