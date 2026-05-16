from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command


def test_alembic_upgrade_creates_expected_tables(tmp_path) -> None:
    database_path = tmp_path / "migration.db"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(config, "head")

    inspector = inspect(create_engine(f"sqlite+pysqlite:///{database_path}"))
    assert {
        "auth_sessions",
        "channels",
        "snapshot_assets",
        "snapshots",
        "liquidation_positions",
        "liquidation_margin_balances",
    } <= set(inspector.get_table_names())


def test_alembic_upgrade_adopts_existing_pre_alembic_database(tmp_path) -> None:
    database_path = tmp_path / "existing.db"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    metadata = sa.MetaData()
    channels = sa.Table(
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
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_value_usd", sa.Numeric(24, 8), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    sa.Table(
        "snapshot_assets",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("snapshots.id"), nullable=False),
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
    created_at = datetime(2026, 5, 9, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            channels.insert().values(
                name="Existing Binance",
                provider="binance",
                kind="cex",
                enabled=True,
                public_config_json="{}",
                secret_config_encrypted="{}",
                created_at=created_at,
                updated_at=created_at,
            )
        )

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "auth_sessions" in inspector.get_table_names()
    with engine.connect() as connection:
        assert connection.scalar(text("select count(*) from channels")) == 1
        assert connection.scalar(text("select version_num from alembic_version")) == "20260516_0004"
