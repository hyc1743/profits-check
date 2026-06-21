from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "20260621_0011"
down_revision = "20260609_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if not inspector.has_table("daily_funding_fee_asset_summaries"):
        op.create_table(
            "daily_funding_fee_asset_summaries",
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
            sa.Column("asset", sa.String(length=32), nullable=False),
            sa.Column("amount", sa.Numeric(24, 8), nullable=False),
            sa.Column("records_count", sa.Integer(), nullable=False),
            sa.UniqueConstraint(
                "daily_summary_id",
                "channel_id",
                "asset",
                name="uq_daily_funding_asset",
            ),
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if inspector.has_table("daily_funding_fee_asset_summaries"):
        op.drop_table("daily_funding_fee_asset_summaries")
