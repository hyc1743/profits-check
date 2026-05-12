from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "20260512_0003"
down_revision = "20260512_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if inspect(op.get_bind()).has_table("liquidation_positions"):
        return
    op.create_table(
        "liquidation_positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("channel_name", sa.String(length=120), nullable=False),
        sa.Column("symbol", sa.String(length=80), nullable=False),
        sa.Column("side", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("entry_price", sa.Numeric(32, 12), nullable=True),
        sa.Column("mark_price", sa.Numeric(32, 12), nullable=False),
        sa.Column("liquidation_price", sa.Numeric(32, 12), nullable=True),
        sa.Column("distance_percent", sa.Numeric(24, 8), nullable=True),
        sa.Column("threshold_percent", sa.Numeric(24, 8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(24, 8), nullable=True),
        sa.Column("margin_mode", sa.String(length=32), nullable=True),
        sa.Column("leverage", sa.String(length=32), nullable=True),
        sa.Column("last_alert_status", sa.String(length=32), nullable=True),
        sa.Column("last_alert_error", sa.Text(), nullable=True),
        sa.Column("last_alert_at", sa.DateTime(), nullable=True),
        sa.Column("source_updated_at_ms", sa.Integer(), nullable=True),
        sa.Column("raw_payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_liquidation_positions_channel_symbol_side",
        "liquidation_positions",
        ["channel_id", "symbol", "side"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_liquidation_positions_channel_symbol_side",
        table_name="liquidation_positions",
    )
    op.drop_table("liquidation_positions")
