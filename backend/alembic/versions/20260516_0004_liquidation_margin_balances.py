from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "20260516_0004"
down_revision = "20260512_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if inspect(op.get_bind()).has_table("liquidation_margin_balances"):
        return
    op.create_table(
        "liquidation_margin_balances",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("channel_name", sa.String(length=120), nullable=False),
        sa.Column("wallet_balance", sa.Numeric(24, 8), nullable=False),
        sa.Column("margin_balance", sa.Numeric(24, 8), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(24, 8), nullable=False),
        sa.Column("risk_percent", sa.Numeric(24, 8), nullable=True),
        sa.Column("threshold_percent", sa.Numeric(24, 8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_alert_status", sa.String(length=32), nullable=True),
        sa.Column("last_alert_error", sa.Text(), nullable=True),
        sa.Column("last_alert_at", sa.DateTime(), nullable=True),
        sa.Column("raw_payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_liquidation_margin_balances_channel_id",
        "liquidation_margin_balances",
        ["channel_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_liquidation_margin_balances_channel_id",
        table_name="liquidation_margin_balances",
    )
    op.drop_table("liquidation_margin_balances")
