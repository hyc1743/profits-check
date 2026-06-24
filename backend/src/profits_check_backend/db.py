from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from profits_check_backend.config import AppSettings, get_database_url
from profits_check_backend.models import Base


class WriteLockedSession(Session):
    def commit(self) -> None:
        write_lock = self.info.get("write_lock")
        if write_lock is None:
            super().commit()
            return
        with write_lock:
            super().commit()


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


def is_sqlite_database(database_url: str) -> bool:
    return make_url(database_url).get_backend_name() == "sqlite"


def configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
    finally:
        cursor.close()


def build_engine(settings: AppSettings):
    database_url = get_database_url(settings)
    ensure_sqlite_parent_directory(database_url)
    connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite_database(database_url) else {}
    engine = create_engine(database_url, future=True, connect_args=connect_args)
    if is_sqlite_database(database_url):
        event.listen(engine, "connect", configure_sqlite_connection)
    return engine


def build_session_factory(settings: AppSettings) -> sessionmaker[Session]:
    database_url = get_database_url(settings)
    session_options = {
        "bind": build_engine(settings),
        "autoflush": False,
        "autocommit": False,
        "future": True,
    }
    if is_sqlite_database(database_url):
        session_options["class_"] = WriteLockedSession
        session_options["info"] = {"write_lock": threading.RLock()}
    return sessionmaker(**session_options)


def init_database(session_factory: sessionmaker[Session]) -> None:
    engine = session_factory.kw["bind"]
    if run_alembic_migrations(engine.url.render_as_string(hide_password=False)):
        return
    Base.metadata.create_all(bind=engine)


def run_alembic_migrations(database_url: str) -> bool:
    backend_root = Path(__file__).resolve().parents[2]
    alembic_ini = backend_root / "alembic.ini"
    alembic_dir = backend_root / "alembic"
    if not alembic_ini.exists() or not alembic_dir.exists():
        return False

    config = Config(str(alembic_ini))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(alembic_dir))
    config.set_main_option("sqlalchemy.url", database_url)
    logging.getLogger("alembic").setLevel(logging.ERROR)
    command.upgrade(config, "head")
    return True


def get_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session
