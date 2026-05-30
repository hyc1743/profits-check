from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "20260530_0007"
down_revision = "20260520_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if not inspector.has_table("adl_position_samples"):
        op.create_table(
            "adl_position_samples",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("channel_name", sa.String(length=120), nullable=False),
            sa.Column("symbol", sa.String(length=80), nullable=False),
            sa.Column("side", sa.String(length=32), nullable=False),
            sa.Column("quantity_abs", sa.Numeric(24, 8), nullable=False),
            sa.Column("sampled_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_adl_position_samples_key_time",
            "adl_position_samples",
            ["channel_id", "symbol", "side", "sampled_at"],
            unique=False,
        )
    if not inspector.has_table("adl_events"):
        op.create_table(
            "adl_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("channel_name", sa.String(length=120), nullable=False),
            sa.Column("symbol", sa.String(length=80), nullable=False),
            sa.Column("side", sa.String(length=32), nullable=False),
            sa.Column("previous_quantity_abs", sa.Numeric(24, 8), nullable=False),
            sa.Column("current_quantity_abs", sa.Numeric(24, 8), nullable=False),
            sa.Column("drop_percent", sa.Numeric(24, 8), nullable=False),
            sa.Column("threshold_percent", sa.Numeric(24, 8), nullable=False),
            sa.Column("window_seconds", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("last_alert_status", sa.String(length=32), nullable=True),
            sa.Column("last_alert_error", sa.Text(), nullable=True),
            sa.Column("last_alert_at", sa.DateTime(), nullable=True),
            sa.Column("detected_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_adl_events_key_detected_at",
            "adl_events",
            ["channel_id", "symbol", "side", "detected_at"],
            unique=False,
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if inspector.has_table("adl_events"):
        op.drop_index("ix_adl_events_key_detected_at", table_name="adl_events")
        op.drop_table("adl_events")
    if inspector.has_table("adl_position_samples"):
        op.drop_index("ix_adl_position_samples_key_time", table_name="adl_position_samples")
        op.drop_table("adl_position_samples")
