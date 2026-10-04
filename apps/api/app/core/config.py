from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    service_name: str = "ark-cloud-api"
    system_hostname: str = "API runtime"
    system_os_name: str = "Linux"
    system_storage_path: str = "/"
    tailscale_api_key: SecretStr | None = None
    tailscale_tailnet: str = "-"
    tailscale_secret_directory: str = "/run/ark-secrets"
    tailscale_controller_directory: str = "/run/ark-tailscale"
    session_secret: SecretStr | None = None
    cookie_secure: bool = False
    session_max_age_seconds: int = 86_400
    storage_manifest: str = "/etc/ark-storage/manifest.json"
    storage_upload_max_bytes: int = Field(default=1_073_741_824, ge=1, le=10_737_418_240)

    @field_validator("system_hostname", "system_os_name", mode="before")
    @classmethod
    def normalize_runtime_label(cls, value: object, info: ValidationInfo) -> object:
        default = "API runtime" if info.field_name == "system_hostname" else "Linux"
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip() or default
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ARK_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
