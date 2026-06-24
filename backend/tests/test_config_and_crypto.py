from __future__ import annotations

import threading
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import inspect

from profits_check_backend.config import AppSettings
from profits_check_backend.db import build_session_factory, init_database
from profits_check_backend.security import SecretCipher


def test_settings_load_from_environment() -> None:
    settings = AppSettings()

    assert settings.database_url.endswith(".db")
    assert settings.scheduler_enabled is True


def test_secret_cipher_round_trip() -> None:
    cipher = SecretCipher.from_settings(AppSettings())

    encrypted = cipher.encrypt("binance-secret")

    assert encrypted != "binance-secret"
    assert cipher.decrypt(encrypted) == "binance-secret"


def test_sqlite_parent_directory_is_created_for_missing_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PROFITS_CHECK_DATABASE_URL", raising=False)
    target_dir = tmp_path / "missing" / "nested"
    settings = AppSettings(
        database_url=f"sqlite:///{target_dir / 'app.db'}",
    )

    session_factory = build_session_factory(settings)
    init_database(session_factory)

    assert target_dir.exists()
    assert (target_dir / "app.db").exists()


def test_sqlite_engine_uses_wal_and_busy_timeout(tmp_path: Path) -> None:
    database_path = tmp_path / "wal.db"
    session_factory = build_session_factory(
        AppSettings(database_url=f"sqlite+pysqlite:///{database_path}")
    )
    engine = session_factory.kw["bind"]

    with engine.connect() as connection:
        journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar()
        busy_timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()

    assert journal_mode == "wal"
    assert busy_timeout == 30000


def test_sqlite_session_commits_are_serialized(tmp_path: Path) -> None:
    database_path = tmp_path / "serialized.db"
    session_factory = build_session_factory(
        AppSettings(database_url=f"sqlite+pysqlite:///{database_path}")
    )
    session = session_factory()
    write_lock = session.info["write_lock"]
    committed = threading.Event()
    errors: list[BaseException] = []

    def commit_in_another_thread() -> None:
        try:
            with session_factory() as other_session:
                other_session.commit()
        except BaseException as exc:
            errors.append(exc)
        finally:
            committed.set()

    write_lock.acquire()
    try:
        thread = threading.Thread(target=commit_in_another_thread)
        thread.start()
        assert not committed.wait(timeout=0.05)
    finally:
        write_lock.release()
        session.close()

    thread.join(timeout=1)
    assert committed.is_set()
    assert errors == []


def test_sqlite_session_flushes_are_serialized(tmp_path: Path) -> None:
    database_path = tmp_path / "serialized-flush.db"
    session_factory = build_session_factory(
        AppSettings(database_url=f"sqlite+pysqlite:///{database_path}")
    )
    session = session_factory()
    write_lock = session.info["write_lock"]
    flushed = threading.Event()
    errors: list[BaseException] = []

    def flush_in_another_thread() -> None:
        try:
            with session_factory() as other_session:
                other_session.flush()
        except BaseException as exc:
            errors.append(exc)
        finally:
            flushed.set()

    write_lock.acquire()
    try:
        thread = threading.Thread(target=flush_in_another_thread)
        thread.start()
        assert not flushed.wait(timeout=0.05)
    finally:
        write_lock.release()
        session.close()

    thread.join(timeout=1)
    assert flushed.is_set()
    assert errors == []


def test_sqlite_write_lock_is_shared_by_session_factories(tmp_path: Path) -> None:
    database_path = tmp_path / "shared-lock.db"
    settings = AppSettings(database_url=f"sqlite+pysqlite:///{database_path}")
    first_factory = build_session_factory(settings)
    second_factory = build_session_factory(settings)
    session = first_factory()
    write_lock = session.info["write_lock"]
    committed = threading.Event()
    errors: list[BaseException] = []

    def commit_from_second_factory() -> None:
        try:
            with second_factory() as other_session:
                other_session.commit()
        except BaseException as exc:
            errors.append(exc)
        finally:
            committed.set()

    write_lock.acquire()
    try:
        thread = threading.Thread(target=commit_from_second_factory)
        thread.start()
        assert not committed.wait(timeout=0.05)
    finally:
        write_lock.release()
        session.close()

    thread.join(timeout=1)
    assert committed.is_set()
    assert errors == []


def test_sqlite_flush_holds_write_lock_until_transaction_finishes(tmp_path: Path) -> None:
    database_path = tmp_path / "flush-transaction.db"
    session_factory = build_session_factory(
        AppSettings(database_url=f"sqlite+pysqlite:///{database_path}")
    )
    session = session_factory()
    committed = threading.Event()
    errors: list[BaseException] = []

    def commit_in_another_session() -> None:
        try:
            with session_factory() as other_session:
                other_session.commit()
        except BaseException as exc:
            errors.append(exc)
        finally:
            committed.set()

    try:
        session.flush()
        thread = threading.Thread(target=commit_in_another_session)
        thread.start()
        assert not committed.wait(timeout=0.05)
    finally:
        session.rollback()
        session.close()

    thread.join(timeout=1)
    assert committed.is_set()
    assert errors == []


def test_init_database_migrates_existing_sqlite_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "existing.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{database_path}")
    metadata = sa.MetaData()
    sa.Table(
        "channels",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("public_config_json", sa.Text(), nullable=False),
        sa.Column("secret_config_encrypted", sa.Text(), nullable=False),
        sa.Column("last_test_status", sa.String(length=32), nullable=True),
        sa.Column("last_test_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    sa.Table(
        "snapshots",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_value_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    sa.Table(
        "snapshot_assets",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("account_scope", sa.String(length=200), nullable=False),
        sa.Column("asset_symbol", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("available", sa.Numeric(24, 8), nullable=False),
        sa.Column("locked", sa.Numeric(24, 8), nullable=False),
        sa.Column("borrowed", sa.Numeric(24, 8), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(24, 8), nullable=False),
        sa.Column("value_usd", sa.Numeric(24, 8), nullable=True),
        sa.Column("raw_payload_json", sa.Text(), nullable=False),
    )
    sa.Table(
        "app_settings",
        metadata,
        sa.Column("key", sa.String(length=120), primary_key=True),
        sa.Column("value_json", sa.Text(), nullable=False),
    )
    metadata.create_all(engine)

    session_factory = build_session_factory(
        AppSettings(database_url=f"sqlite+pysqlite:///{database_path}")
    )
    init_database(session_factory)

    engine.dispose()
    migrated_engine = sa.create_engine(f"sqlite+pysqlite:///{database_path}")
    inspector = inspect(migrated_engine)
    snapshot_asset_columns = {column["name"] for column in inspector.get_columns("snapshot_assets")}
    assert {"inclusion_key", "included_in_totals"} <= snapshot_asset_columns
    assert "monthly_funding_fee_summaries" in inspector.get_table_names()
