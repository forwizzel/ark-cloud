import os

import pytest
from argon2 import PasswordHasher
from sqlalchemy.orm import Session

os.environ["ARK_DATABASE_URL"] = "sqlite://"
os.environ["ARK_ENVIRONMENT"] = "test"
os.environ["ARK_AUTH_USERNAME"] = "ark"
os.environ["ARK_AUTH_PASSWORD_HASH"] = PasswordHasher().hash("test-password")
os.environ["ARK_SESSION_SECRET"] = "test-session-secret"
os.environ["ARK_TAILSCALE_API_KEY"] = ""


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    from app.core.database import engine
    from app.models import Base

    Base.metadata.create_all(engine)
    yield

    from app.main import app

    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


@pytest.fixture
def db_session() -> Session:
    from app.core.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
