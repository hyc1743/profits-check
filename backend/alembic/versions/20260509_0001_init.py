from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "20260509_0001"
down_revision = None
branch_labels = None
depends_on = None


def table_exists(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not table_exists("channels"):
        op.create_table(
            "channels",
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
    if not table_exists("snapshots"):
        op.create_table(
            "snapshots",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("total_value_usd", sa.Numeric(24, 8), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if not table_exists("snapshot_assets"):
        op.create_table(
            "snapshot_assets",
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
    if not table_exists("app_settings"):
        op.create_table(
            "app_settings",
            sa.Column("key", sa.String(length=120), primary_key=True),
            sa.Column("value_json", sa.Text(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_table("snapshot_assets")
    op.drop_table("snapshots")
    op.drop_table("channels")
