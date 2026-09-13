import os

import pytest

os.environ["ARK_DATABASE_URL"] = "sqlite://"
os.environ["ARK_ENVIRONMENT"] = "test"


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    yield

    from app.main import app

    app.dependency_overrides.clear()
