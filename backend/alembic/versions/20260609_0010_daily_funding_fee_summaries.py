from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "20260609_0010"
down_revision = "20260609_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if not inspector.has_table("daily_funding_fee_summaries"):
        op.create_table(
            "daily_funding_fee_summaries",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("date", sa.String(length=10), nullable=False, unique=True),
            sa.Column("start_time", sa.DateTime(), nullable=False),
            sa.Column("end_time", sa.DateTime(), nullable=False),
            sa.Column("received", sa.Numeric(24, 8), nullable=False),
            sa.Column("paid", sa.Numeric(24, 8), nullable=False),
            sa.Column("net", sa.Numeric(24, 8), nullable=False),
            sa.Column("records_count", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not inspector.has_table("daily_funding_fee_channel_summaries"):
        op.create_table(
            "daily_funding_fee_channel_summaries",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "daily_summary_id",
                sa.Integer(),
                sa.ForeignKey("daily_funding_fee_summaries.id"),
                nullable=False,
            ),
            sa.Column("channel_id", sa.Integer(), nullable=False),
            sa.Column("channel_name", sa.String(length=120), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("received", sa.Numeric(24, 8), nullable=False),
            sa.Column("paid", sa.Numeric(24, 8), nullable=False),
            sa.Column("net", sa.Numeric(24, 8), nullable=False),
            sa.Column("records_count", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.UniqueConstraint(
                "daily_summary_id",
                "channel_id",
                name="uq_daily_funding_channel",
            ),
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if inspector.has_table("daily_funding_fee_channel_summaries"):
        op.drop_table("daily_funding_fee_channel_summaries")
    if inspector.has_table("daily_funding_fee_summaries"):
        op.drop_table("daily_funding_fee_summaries")
