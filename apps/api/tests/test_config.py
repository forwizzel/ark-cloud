from app.core.config import Settings


def test_settings_load_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("ARK_DATABASE_URL", "postgresql+psycopg://user:pass@db/example")
    monkeypatch.setenv("ARK_LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.database_url.endswith("@db/example")
    assert settings.log_level == "DEBUG"
    assert settings.service_name == "ark-cloud-api"
