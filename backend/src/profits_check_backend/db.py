from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from profits_check_backend.config import AppSettings, get_database_url
from profits_check_backend.models import Base


def ensure_sqlite_parent_directory(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return

    database_name = make_url(database_url).database
    if database_name is None:
        return

    database_path = Path(database_name)
    if not database_path.is_absolute():
        database_path = Path.cwd() / database_path

    database_path.parent.mkdir(parents=True, exist_ok=True)


def build_engine(settings: AppSettings):
    database_url = get_database_url(settings)
    ensure_sqlite_parent_directory(database_url)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, connect_args=connect_args)


def build_session_factory(settings: AppSettings) -> sessionmaker[Session]:
    return sessionmaker(bind=build_engine(settings), autoflush=False, autocommit=False, future=True)


def init_database(session_factory: sessionmaker[Session]) -> None:
    Base.metadata.create_all(bind=session_factory.kw["bind"])


def get_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session
