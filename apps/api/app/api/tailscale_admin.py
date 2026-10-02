"""Administrator configuration and a separate authenticated node controller protocol."""

import re
import secrets
from contextlib import suppress
from datetime import timedelta
from http.client import HTTPException as HTTPClientError
from typing import Annotated, Literal
from urllib.error import HTTPError
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy.orm import Session

from app.auth.service import Principal, token_hash
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.dependencies import require_admin
from app.models import LocalUser, TailscaleControl
from app.services.tailscale_control import (
    TailnetClient,
    control,
    credentials,
    decrypt,
    encrypt,
    now,
)

router = APIRouter(prefix="/admin/tailscale", tags=["Tailscale administration"])
Database = Annotated[Session, Depends(get_db_session)]
Configuration = Annotated[Settings, Depends(get_settings)]
Administrator = Annotated[Principal, Depends(require_admin)]
States = Literal[
    "offline", "connecting", "approval_required", "connected", "disabled", "disconnected", "error"
]
UPSTREAM_ERRORS = (OSError, HTTPClientError, ValueError, KeyError, TypeError)


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    api_key: SecretStr = Field(min_length=1, max_length=4096)

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value: SecretStr):
        key = value.get_secret_value().strip()
        if not key.startswith("tskey-api-") or any(char.isspace() for char in key):
            raise ValueError("Enter a Tailscale API key.")
        return SecretStr(key)


class ControllerReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    state: States
    message: str = Field(max_length=500)
    node_id: str | None = Field(default=None, max_length=128)
    dns_name: str | None = Field(default=None, max_length=253)
    serve_url: str | None = Field(default=None, max_length=512)
    approval_url: str | None = Field(default=None, max_length=2048)


class AdminStatus(BaseModel):
    configured: bool
    source: Literal["ui", "environment", "none"]
    integration_state: Literal["available", "unavailable", "not_configured"]
    integration_message: str | None
    desired_enabled: bool
    revision: int
    state: States
    message: str
    serve_url: str | None
    approval_url: str | None
    dns_name: str | None
    node_id: str | None
    controller_online: bool


def view(value: TailscaleControl | None, settings: Settings, response: Response):
    response.headers["Cache-Control"] = "no-store"
    key, _, source = credentials(value, settings)
    snapshot = value.snapshot if value else {}
    online = bool(
        value
        and value.last_seen_at
        and now() - value.last_seen_at.replace(tzinfo=now().tzinfo) < timedelta(seconds=45)
    )
    state = snapshot.get("state", "offline")
    message = snapshot.get("message", "Connect Tailscale to enable private remote access.")
    if value and value.desired_enabled and not online:
        state, message = "offline", "Waiting for ArkCloud's managed Tailscale service."
    return AdminStatus(
        configured=bool(key),
        source=source,
        integration_state=value.integration_state
        if value and (value.configured_override or value.integration_checked_at)
        else "available"
        if key
        else "not_configured",
        integration_message=value.integration_message if value else None,
        desired_enabled=bool(value and value.desired_enabled),
        revision=value.revision if value else 0,
        state=state,
        message=message,
        serve_url=snapshot.get("serve_url") if online and state == "connected" else None,
        approval_url=snapshot.get("approval_url")
        if online and state == "approval_required"
        else None,
        dns_name=snapshot.get("dns_name"),
        node_id=snapshot.get("node_id"),
        controller_online=online,
    )


def upstream_failure(error):
    if isinstance(error, HTTPError) and error.code in (401, 403):
        return (
            "Tailscale rejected this key or its permissions. "
            "Use an API key allowed to register devices."
        )
    return "Tailscale could not be reached or returned an invalid response. Retry the connection."


def update_desire(value, principal, *, enabled, disconnect=False):
    value.revision += 1
    value.principal_id = principal.id
    value.desired_enabled = enabled
    value.disconnect = disconnect
    # Old observed URLs must never masquerade as the new operation's result.
    value.snapshot = {
        **value.snapshot,
        "state": "connecting",
        "message": "Applying Tailscale configuration.",
        "serve_url": None,
        "approval_url": None,
    }


def clear_auth_key(value):
    value.auth_key_encrypted = None
    value.auth_key_id = None
    value.auth_key_expires_at = None


def revoke_pending(value, settings):
    if value.auth_key_id:
        key, tailnet, _ = credentials(value, settings)
        if key:
            # Single-use keys expire upstream even when revocation is unavailable.
            with suppress(*UPSTREAM_ERRORS):
                TailnetClient(key, tailnet).revoke_auth_key(value.auth_key_id)
    clear_auth_key(value)


@router.get("", response_model=AdminStatus)
def status(_principal: Administrator, db: Database, settings: Configuration, response: Response):
    value = db.get(TailscaleControl, 1)
    key, tailnet, _ = credentials(value, settings)
    if (
        key
        and value
        and (
            value.integration_checked_at is None
            or now() - value.integration_checked_at.replace(tzinfo=now().tzinfo)
            > timedelta(minutes=5)
        )
    ):
        value = control(db)
        key, tailnet, _ = credentials(value, settings)
        if not key:
            return view(value, settings, response)
        try:
            TailnetClient(key, tailnet).validate(value.snapshot.get("node_id"))
            value.integration_state = "available"
            value.integration_message = "API key verified. Device inventory is available."
        except UPSTREAM_ERRORS as error:
            value.integration_state = "unavailable"
            value.integration_message = upstream_failure(error)
        except HTTPException:
            value.integration_state = "unavailable"
            value.integration_message = (
                "The saved key cannot access ArkCloud's managed node. Replace the key."
            )
        value.integration_checked_at = now()
        db.commit()
    return view(value, settings, response)


@router.post("/connect", response_model=AdminStatus)
def connect(
    payload: ConnectRequest,
    principal: Administrator,
    db: Database,
    settings: Configuration,
    response: Response,
):
    value = control(db)
    key = payload.api_key.get_secret_value()
    client = TailnetClient(key)
    try:
        # Prevent a replacement key from leaving inventory and Serve on different tailnets.
        client.validate(value.snapshot.get("node_id"))
    except UPSTREAM_ERRORS as error:
        raise HTTPException(422, upstream_failure(error)) from None
    # Encryption must succeed before replacing working credentials.
    encrypted = encrypt(settings, key)
    revoke_pending(value, settings)
    value.api_key_encrypted = encrypted
    value.tailnet = "-"
    value.configured_override = True
    value.integration_state = "available"
    value.integration_message = "API key verified. Device inventory is available."
    value.integration_checked_at = now()
    update_desire(value, principal, enabled=True)
    db.commit()
    return view(value, settings, response)


@router.post("/enable", response_model=AdminStatus)
def enable(principal: Administrator, db: Database, settings: Configuration, response: Response):
    value = control(db)
    key, tailnet, source = credentials(value, settings)
    if not key:
        raise HTTPException(409, "Connect a Tailscale API key first.")
    if source == "environment":
        # Explicit UI enable adopts legacy credentials; startup never enables them.
        try:
            TailnetClient(key, tailnet).validate(value.snapshot.get("node_id"))
        except UPSTREAM_ERRORS as error:
            raise HTTPException(422, upstream_failure(error)) from None
        value.api_key_encrypted = encrypt(settings, key)
        value.tailnet = tailnet
        value.configured_override = True
        value.integration_state = "available"
        value.integration_message = "API key verified. Device inventory is available."
        value.integration_checked_at = now()
    update_desire(value, principal, enabled=True)
    db.commit()
    return view(value, settings, response)


@router.post("/disable", response_model=AdminStatus)
def disable(principal: Administrator, db: Database, settings: Configuration, response: Response):
    value = control(db)
    revoke_pending(value, settings)
    update_desire(value, principal, enabled=False)
    db.commit()
    return view(value, settings, response)


@router.post("/disconnect", response_model=AdminStatus)
def disconnect(principal: Administrator, db: Database, settings: Configuration, response: Response):
    value = control(db)
    revoke_pending(value, settings)
    value.api_key_encrypted = None
    value.configured_override = True
    value.integration_state = "not_configured"
    value.integration_message = "API key removed."
    update_desire(value, principal, enabled=False, disconnect=True)
    db.commit()
    return view(value, settings, response)


@router.post("/test", response_model=AdminStatus)
def test_connection(
    _principal: Administrator, db: Database, settings: Configuration, response: Response
):
    value = control(db)
    key, tailnet, _ = credentials(value, settings)
    if not key:
        raise HTTPException(409, "Connect a Tailscale API key first.")
    try:
        TailnetClient(key, tailnet).validate(value.snapshot.get("node_id"))
        value.integration_state = "available"
        value.integration_message = "API key verified. Device inventory is available."
    except UPSTREAM_ERRORS as error:
        value.integration_state = "unavailable"
        value.integration_message = upstream_failure(error)
    except HTTPException:
        value.integration_state = "unavailable"
        value.integration_message = (
            "The saved key cannot access ArkCloud's managed node. Replace the key."
        )
    value.integration_checked_at = now()
    db.commit()
    return view(value, settings, response)


def require_controller(request: Request, db: Database):
    header = request.headers.get("Authorization", "")
    value = db.get(TailscaleControl, 1)
    if (
        not value
        or not value.token_hash
        or not header.startswith("Bearer ")
        or not secrets.compare_digest(token_hash(header[7:]), value.token_hash)
    ):
        raise HTTPException(401, "Controller authentication required.")
    return value


Controller = Annotated[TailscaleControl, Depends(require_controller)]


@router.get("/controller/work")
def work(
    value: Controller,
    db: Database,
    settings: Configuration,
    response: Response,
    needs_auth: bool = False,
):
    value = control(db)
    response.headers["Cache-Control"] = "no-store"
    if value.principal_id:
        user = db.get(LocalUser, value.principal_id)
        if not user or not user.active or user.role != "admin":
            revoke_pending(value, settings)
            value.desired_enabled = False
            value.revision += 1
            value.principal_id = None
            value.snapshot = {
                "state": "error",
                "message": "The requesting administrator no longer has access.",
            }
    auth_key = None
    if value.desired_enabled and not value.disconnect and needs_auth:
        key, tailnet, _ = credentials(value, settings)
        if key:
            client = TailnetClient(key, tailnet)
            if (
                value.auth_key_expires_at
                and value.auth_key_expires_at.replace(tzinfo=now().tzinfo) <= now()
            ):
                revoke_pending(value, settings)
            if not value.auth_key_encrypted:
                try:
                    secret, key_id = client.create_auth_key()
                    value.auth_key_encrypted = encrypt(settings, secret)
                    value.auth_key_id = key_id
                    value.auth_key_expires_at = now() + timedelta(minutes=10)
                except UPSTREAM_ERRORS as error:
                    value.integration_state = "unavailable"
                    value.integration_message = upstream_failure(error)
                    value.integration_checked_at = now()
                    value.snapshot = {"state": "error", "message": value.integration_message}
                    value.last_seen_at = now()
                    db.commit()
                    raise HTTPException(503, value.integration_message) from None
            auth_key = decrypt(settings, value.auth_key_encrypted)
    db.commit()
    return {
        "revision": value.revision,
        "desired_enabled": value.desired_enabled,
        "disconnect": value.disconnect,
        "auth_key": auth_key,
        "hostname": "arkcloud",
    }


@router.post("/controller/report")
def report(payload: ControllerReport, _value: Controller, db: Database, response: Response):
    value = control(db)
    response.headers["Cache-Control"] = "no-store"
    if payload.revision != value.revision:
        raise HTTPException(409, "Tailscale configuration changed. Reconcile the current revision.")
    if payload.dns_name and not re.fullmatch(
        r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+ts\.net", payload.dns_name
    ):
        raise HTTPException(422, "Invalid Tailscale DNS name.")
    if payload.serve_url and payload.serve_url != f"https://{payload.dns_name}":
        raise HTTPException(422, "Invalid private access address.")
    if payload.approval_url:
        parsed = urlsplit(payload.approval_url)
        if (
            parsed.scheme != "https"
            or parsed.netloc not in {"login.tailscale.com", "console.tailscale.com"}
            or not parsed.path.startswith(("/a/", "/f/", "/admin/"))
            or parsed.fragment
        ):
            raise HTTPException(422, "Invalid Tailscale approval address.")
    if payload.state == "connected" and (
        not value.desired_enabled
        or value.disconnect
        or not payload.dns_name
        or not payload.serve_url
        or not payload.node_id
    ):
        raise HTTPException(409, "Remote access has not been enabled and verified.")
    if payload.state == "disconnected" and not value.disconnect:
        raise HTTPException(409, "Node disconnection has not been requested.")
    if payload.state == "disabled" and (value.desired_enabled or value.disconnect):
        raise HTTPException(409, "Disabling remote access has not been requested.")
    if payload.state == "approval_required" and not payload.approval_url:
        raise HTTPException(422, "An approved Tailscale consent address is required.")
    value.snapshot = payload.model_dump(exclude={"revision"})
    value.last_seen_at = now()
    if payload.node_id and payload.state in {"connected", "approval_required"}:
        clear_auth_key(value)
    if payload.state in {"connected", "disabled", "disconnected"}:
        value.principal_id = None
    db.commit()
    return {"accepted": True}
