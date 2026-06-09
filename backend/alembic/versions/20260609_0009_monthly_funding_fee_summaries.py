from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "20260609_0009"
down_revision = "20260531_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if inspector.has_table("monthly_funding_fee_summaries"):
        return
    op.create_table(
        "monthly_funding_fee_summaries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("month", sa.String(length=7), nullable=False, unique=True),
        sa.Column("start_date", sa.String(length=10), nullable=False),
        sa.Column("end_date", sa.String(length=10), nullable=False),
        sa.Column("received", sa.Numeric(24, 8), nullable=False),
        sa.Column("paid", sa.Numeric(24, 8), nullable=False),
        sa.Column("net", sa.Numeric(24, 8), nullable=False),
        sa.Column("records_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if inspector.has_table("monthly_funding_fee_summaries"):
        op.drop_table("monthly_funding_fee_summaries")
