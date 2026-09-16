from collections.abc import Generator
from typing import Literal

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.logging import get_logger

DatabaseState = Literal["connected", "disconnected"]


def create_database_engine(database_url: str) -> Engine:
    connect_args = {"connect_timeout": 2} if database_url.startswith("postgresql") else {}
    if database_url == "sqlite://":
        connect_args = {"check_same_thread": False}
    return create_engine(
        database_url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args=connect_args,
        poolclass=StaticPool if database_url == "sqlite://" else None,
    )


engine = create_database_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db_session() -> Generator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


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
