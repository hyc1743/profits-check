from __future__ import annotations

import contextlib
import fcntl
import logging
import threading
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType
from typing import TextIO

from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from profits_check_backend.config import AppSettings, get_database_url
from profits_check_backend.models import Base


class SQLiteWriteLock:
    def __init__(self, lock_path: Path | None) -> None:
        self._lock_path = lock_path
        self._thread_lock = threading.Lock()
        self._lock_file: TextIO | None = None

    def acquire(self) -> None:
        self._thread_lock.acquire()
        if self._lock_path is None:
            return
        try:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = self._lock_path.open("a+")
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except BaseException:
                lock_file.close()
                raise
            self._lock_file = lock_file
        except BaseException:
            self._thread_lock.release()
            raise

    def release(self) -> None:
        try:
            if self._lock_file is not None:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
                self._lock_file = None
        finally:
            self._thread_lock.release()

    def __enter__(self) -> SQLiteWriteLock:
        self.acquire()
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.release()


_SQLITE_WRITE_LOCKS: dict[Path, SQLiteWriteLock] = {}
_SQLITE_WRITE_LOCKS_GUARD = threading.Lock()


class WriteLockedSession(Session):
    def execute(self, statement, *args, **kwargs):
        # Core DML run via Session.execute() (e.g. delete()/update()/insert())
        # issues SQL straight to SQLite without going through flush()/commit().
        # Acquire the write lock first so every writer takes the lock BEFORE the
        # SQLite write lock, keeping a single consistent lock order (no AB-BA
        # deadlock between this Python lock and SQLite's own write lock).
        if getattr(statement, "is_dml", False):
            self._acquire_write_lock()
        return super().execute(statement, *args, **kwargs)

    def flush(self, objects=None) -> None:
        self._acquire_write_lock()
        super().flush(objects)

    def commit(self) -> None:
        self._acquire_write_lock()
        try:
            super().commit()
        finally:
            self._release_write_lock()

    def rollback(self) -> None:
        try:
            super().rollback()
        finally:
            self._release_write_lock()

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._release_write_lock()

    def _acquire_write_lock(self) -> None:
        if self.info.get("write_lock_held"):
            return
        write_lock = self.info.get("write_lock")
        if write_lock is None:
            return
        write_lock.acquire()
        self.info["write_lock_held"] = True

    def _release_write_lock(self) -> None:
        if not self.info.get("write_lock_held"):
            return
        write_lock = self.info.get("write_lock")
        self.info["write_lock_held"] = False
        if write_lock is not None:
            write_lock.release()

    @contextlib.contextmanager
    def write_section(self) -> Iterator[WriteLockedSession]:
        """Run a read-modify-write under the write lock with a fresh snapshot.

        Acquiring the lock *before* any read guarantees no other connection can
        commit while this section runs, so the WAL read snapshot taken inside the
        section stays valid through the write. This avoids SQLITE_BUSY_SNAPSHOT,
        which busy_timeout cannot retry. The section must not perform slow network
        I/O while holding the lock.
        """
        self._acquire_write_lock()
        try:
            # End any read transaction opened before the lock so the body's first
            # read starts a brand-new snapshot. super().rollback() does not release
            # the lock we just acquired (the overridden rollback() would).
            super().rollback()
            yield self
            self.commit()
        except BaseException:
            self.rollback()
            raise
        finally:
            self._release_write_lock()


def ensure_sqlite_parent_directory(database_url: str) -> None:
    database_path = sqlite_database_path(database_url)
    if database_path is None:
        return

    database_path.parent.mkdir(parents=True, exist_ok=True)


def is_sqlite_database(database_url: str) -> bool:
    return make_url(database_url).get_backend_name() == "sqlite"


def sqlite_database_path(database_url: str) -> Path | None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return None
    database_name = url.database
    if database_name is None or database_name in ("", ":memory:"):
        return None
    database_path = Path(database_name)
    if not database_path.is_absolute():
        database_path = Path.cwd() / database_path
    return database_path


def sqlite_write_lock(database_url: str) -> SQLiteWriteLock:
    database_path = sqlite_database_path(database_url)
    if database_path is None:
        return SQLiteWriteLock(None)
    lock_path = database_path.with_name(f"{database_path.name}.write.lock").resolve()
    with _SQLITE_WRITE_LOCKS_GUARD:
        lock = _SQLITE_WRITE_LOCKS.get(lock_path)
        if lock is None:
            lock = SQLiteWriteLock(lock_path)
            _SQLITE_WRITE_LOCKS[lock_path] = lock
        return lock


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
    connect_args = (
        {"check_same_thread": False, "timeout": 30} if is_sqlite_database(database_url) else {}
    )
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
        session_options["info"] = {"write_lock": sqlite_write_lock(database_url)}
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
