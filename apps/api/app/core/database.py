from typing import Literal

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.logging import get_logger

DatabaseState = Literal["connected", "disconnected"]


def create_database_engine(database_url: str) -> Engine:
    connect_args = {"connect_timeout": 2} if database_url.startswith("postgresql") else {}
    return create_engine(
        database_url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args=connect_args,
    )


engine = create_database_engine(get_settings().database_url)


def check_database(database_engine: Engine = engine) -> None:
    with database_engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def get_database_state() -> DatabaseState:
    try:
        check_database()
    except SQLAlchemyError:
        get_logger(__name__).exception("database_health_check_failed")
        return "disconnected"
    return "connected"
