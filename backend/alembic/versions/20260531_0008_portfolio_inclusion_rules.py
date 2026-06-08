from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "20260531_0008"
down_revision = "20260530_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if inspector.has_table("snapshot_assets"):
        columns = {column["name"] for column in inspector.get_columns("snapshot_assets")}
        if "inclusion_key" not in columns:
            op.add_column(
                "snapshot_assets",
                sa.Column("inclusion_key", sa.String(length=260), nullable=True),
            )
        if "included_in_totals" not in columns:
            op.add_column(
                "snapshot_assets",
                sa.Column(
                    "included_in_totals",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                ),
            )

    if not inspector.has_table("portfolio_inclusion_rules"):
        op.create_table(
            "portfolio_inclusion_rules",
            sa.Column("key", sa.String(length=260), primary_key=True),
            sa.Column(
                "included_in_totals",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if inspector.has_table("portfolio_inclusion_rules"):
        op.drop_table("portfolio_inclusion_rules")
    if inspector.has_table("snapshot_assets"):
        columns = {column["name"] for column in inspector.get_columns("snapshot_assets")}
        if "included_in_totals" in columns:
            op.drop_column("snapshot_assets", "included_in_totals")
        if "inclusion_key" in columns:
            op.drop_column("snapshot_assets", "inclusion_key")
