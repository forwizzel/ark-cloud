import json
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from http.client import HTTPException as HTTPClientError
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.base import Integration
from app.models import GoogleDriveConnection
from app.schemas.integrations import GoogleDriveSummary, IntegrationHealth

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ABOUT_URL = "https://www.googleapis.com/drive/v3/about"
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.metadata.readonly"


class GoogleDriveError(RuntimeError):
    """A safe, normalized Google Drive error."""


class GoogleDriveIntegration(Integration):
    integration_id = "google_drive"
    name = "Google Drive"

    def __init__(self, settings: Settings, db: Session) -> None:
        self._settings = settings
        self._db = db

    def summary(self, principal_id: str, force_refresh: bool = False) -> GoogleDriveSummary:
        timestamp = datetime.now(UTC)
        if not self._settings.google_is_configured:
            return GoogleDriveSummary(
                state="not_configured",
                message="Add Google OAuth credentials to enable Drive status.",
                checked_at=timestamp,
            )

        connection = self._db.get(GoogleDriveConnection, principal_id)
        if connection is None:
            return GoogleDriveSummary(
                state="not_configured",
                message="Connect a Google Drive account to enable Drive status.",
                checked_at=timestamp,
            )

        last_checked_at = _as_utc(connection.last_checked_at)
        is_stale = last_checked_at is None or last_checked_at <= timestamp - timedelta(
            seconds=self._settings.google_status_cache_seconds
        )
        if force_refresh or is_stale:
            try:
                self._refresh(connection)
            except GoogleDriveError as error:
                connection.last_error = str(error)
                connection.last_checked_at = timestamp
                connection.updated_at = timestamp
                self._db.commit()

        return self._summary_from_connection(connection, timestamp)

    def health_for(self, summary: GoogleDriveSummary) -> IntegrationHealth:
        return IntegrationHealth(
            id=self.integration_id,
            name=self.name,
            state=summary.state,
            message=summary.message,
            checked_at=summary.checked_at,
        )

    def health(self) -> IntegrationHealth:
        return IntegrationHealth(
            id=self.integration_id,
            name=self.name,
            state="not_configured",
            message="Google Drive status requires an authenticated session.",
            checked_at=datetime.now(UTC),
        )

    def exchange_code(self, principal_id: str, code: str) -> None:
        if not self._settings.google_is_configured:
            raise GoogleDriveError("Google Drive is not configured.")
        response = self._post_form(
            GOOGLE_TOKEN_URL,
            {
                "code": code,
                "client_id": self._settings.google_client_id or "",
                "client_secret": self._settings.google_client_secret.get_secret_value(),
                "redirect_uri": self._settings.google_redirect_uri or "",
                "grant_type": "authorization_code",
            },
        )
        refresh_token = response.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise GoogleDriveError(
                "Google did not return a refresh token. Reconnect and grant consent."
            )

        timestamp = datetime.now(UTC)
        connection = GoogleDriveConnection(
            principal_id=principal_id,
            refresh_token_encrypted=self._encrypt(refresh_token),
            granted_scopes=str(response.get("scope", GOOGLE_DRIVE_SCOPE)),
            created_at=timestamp,
            updated_at=timestamp,
        )
        existing = self._db.get(GoogleDriveConnection, principal_id)
        if existing is not None:
            self._db.delete(existing)
            self._db.flush()
        self._db.add(connection)
        self._db.commit()
        self._refresh(connection)

    def disconnect(self, principal_id: str) -> None:
        connection = self._db.get(GoogleDriveConnection, principal_id)
        if connection is None:
            return
        # Local deletion prevents future API access even if Google is unreachable.
        with suppress(GoogleDriveError):
            self._post_form(
                "https://oauth2.googleapis.com/revoke",
                {"token": self._decrypt(connection.refresh_token_encrypted)},
            )
        self._db.delete(connection)
        self._db.commit()

    def _refresh(self, connection: GoogleDriveConnection) -> None:
        access_token = self._access_token(connection)
        request = Request(
            f"{GOOGLE_ABOUT_URL}?fields=user(displayName,emailAddress),storageQuota(limit,usage)",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        payload = self._request_json(request)
        user = payload.get("user")
        quota = payload.get("storageQuota")
        if not isinstance(user, dict) or not isinstance(quota, dict):
            raise GoogleDriveError("Google Drive returned an unexpected status response.")
        used = _optional_int(quota.get("usage"))
        total = _optional_int(quota.get("limit"))
        timestamp = datetime.now(UTC)
        connection.account_email = _optional_str(user.get("emailAddress"))
        connection.account_name = _optional_str(user.get("displayName"))
        connection.used_bytes = used
        connection.total_bytes = total
        connection.last_checked_at = timestamp
        connection.last_error = None
        connection.updated_at = timestamp
        self._db.commit()

    def _access_token(self, connection: GoogleDriveConnection) -> str:
        response = self._post_form(
            GOOGLE_TOKEN_URL,
            {
                "client_id": self._settings.google_client_id or "",
                "client_secret": self._settings.google_client_secret.get_secret_value(),
                "refresh_token": self._decrypt(connection.refresh_token_encrypted),
                "grant_type": "refresh_token",
            },
        )
        access_token = response.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise GoogleDriveError("Google Drive authorization needs to be reconnected.")
        return access_token

    def _summary_from_connection(
        self, connection: GoogleDriveConnection, fallback_checked_at: datetime
    ) -> GoogleDriveSummary:
        checked_at = _as_utc(connection.last_checked_at) or fallback_checked_at
        if connection.last_error:
            return GoogleDriveSummary(
                state="unavailable",
                account_email=connection.account_email,
                account_name=connection.account_name,
                message=connection.last_error,
                checked_at=checked_at,
            )
        available = None
        percent = None
        if connection.total_bytes is not None and connection.used_bytes is not None:
            available = max(0, connection.total_bytes - connection.used_bytes)
            if connection.total_bytes > 0:
                percent = connection.used_bytes / connection.total_bytes * 100
        return GoogleDriveSummary(
            state="healthy",
            account_email=connection.account_email,
            account_name=connection.account_name,
            used_bytes=connection.used_bytes,
            total_bytes=connection.total_bytes,
            available_bytes=available,
            percent=percent,
            message="Google Drive status is current.",
            checked_at=checked_at,
        )

    def _encrypt(self, value: str) -> str:
        try:
            return (
                Fernet(self._settings.google_token_encryption_key.get_secret_value().encode())
                .encrypt(value.encode())
                .decode()
            )
        except (ValueError, TypeError) as error:
            raise GoogleDriveError(
                "Google token encryption is not configured correctly."
            ) from error

    def _decrypt(self, value: str) -> str:
        try:
            return (
                Fernet(self._settings.google_token_encryption_key.get_secret_value().encode())
                .decrypt(value.encode())
                .decode()
            )
        except (InvalidToken, ValueError, TypeError) as error:
            raise GoogleDriveError("Google Drive authorization needs to be reconnected.") from error

    def _post_form(self, url: str, values: dict[str, str]) -> dict[str, Any]:
        request = Request(
            url,
            data=urlencode(values).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        return self._request_json(request)

    def _request_json(self, request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=5) as response:  # noqa: S310 - fixed Google origins only
                payload = json.loads(response.read(1_000_000))
        except HTTPError as error:
            if error.code in {400, 401}:
                raise GoogleDriveError(
                    "Google Drive authorization needs to be reconnected."
                ) from error
            if error.code == 429:
                raise GoogleDriveError(
                    "Google Drive is rate limiting requests. Try again later."
                ) from error
            raise GoogleDriveError("Google Drive is unavailable.") from error
        except (HTTPClientError, OSError, TimeoutError, URLError, json.JSONDecodeError) as error:
            raise GoogleDriveError("Google Drive is unavailable.") from error
        if not isinstance(payload, dict):
            raise GoogleDriveError("Google Drive returned an unexpected response.")
        return payload


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        number = int(str(value))
    except TypeError, ValueError:
        return None
    return number if number >= 0 else None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
