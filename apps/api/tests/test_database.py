from sqlalchemy import create_engine

from app.core.database import check_database, get_database_state


def test_database_check_executes_query() -> None:
    test_engine = create_engine("sqlite://")

    check_database(test_engine)


def test_configured_test_database_is_connected() -> None:
    assert get_database_state() == "connected"
