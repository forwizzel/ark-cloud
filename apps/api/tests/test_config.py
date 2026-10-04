import pytest

from app.core.config import Settings


def test_settings_load_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("ARK_DATABASE_URL", "postgresql+psycopg://user:pass@db/example")
    monkeypatch.setenv("ARK_LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.database_url.endswith("@db/example")
    assert settings.log_level == "DEBUG"
    assert settings.service_name == "ark-cloud-api"


def test_system_labels_default_to_neutral_runtime_identity(monkeypatch) -> None:
    monkeypatch.delenv("ARK_SYSTEM_HOSTNAME", raising=False)
    monkeypatch.delenv("ARK_SYSTEM_OS_NAME", raising=False)

    settings = Settings(database_url="sqlite://", _env_file=None)

    assert settings.system_hostname == "API runtime"
    assert settings.system_os_name == "Linux"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_environment_labels_use_neutral_defaults(monkeypatch, blank) -> None:
    monkeypatch.setenv("ARK_SYSTEM_HOSTNAME", blank)
    monkeypatch.setenv("ARK_SYSTEM_OS_NAME", blank)

    settings = Settings(database_url="sqlite://", _env_file=None)

    assert settings.system_hostname == "API runtime"
    assert settings.system_os_name == "Linux"


def test_explicit_runtime_labels_are_preserved_and_trimmed(monkeypatch) -> None:
    monkeypatch.setenv("ARK_SYSTEM_HOSTNAME", "  backup-node  ")
    monkeypatch.setenv("ARK_SYSTEM_OS_NAME", "  Ubuntu 24.04 LTS  ")

    settings = Settings(database_url="sqlite://", _env_file=None)

    assert settings.system_hostname == "backup-node"
    assert settings.system_os_name == "Ubuntu 24.04 LTS"
