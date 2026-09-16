from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    service_name: str = "ark-cloud-api"
    system_hostname: str = "Ark"
    system_os_name: str = "Linux"
    system_storage_path: str = "/"
    tailscale_api_key: SecretStr | None = None
    tailscale_tailnet: str = "-"
    auth_username: str | None = None
    auth_password_hash: SecretStr | None = None
    session_secret: SecretStr | None = None
    cookie_secure: bool = False
    session_max_age_seconds: int = 86_400
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str | None = None
    google_token_encryption_key: SecretStr | None = None
    google_status_cache_seconds: int = 300

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ARK_",
        extra="ignore",
    )

    @property
    def auth_is_configured(self) -> bool:
        return bool(
            self.auth_username
            and self.auth_password_hash
            and self.auth_password_hash.get_secret_value()
            and self.session_secret
            and self.session_secret.get_secret_value()
        )

    @property
    def google_is_configured(self) -> bool:
        return bool(
            self.google_client_id
            and self.google_client_secret
            and self.google_client_secret.get_secret_value()
            and self.google_redirect_uri
            and self.google_token_encryption_key
            and self.google_token_encryption_key.get_secret_value()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
