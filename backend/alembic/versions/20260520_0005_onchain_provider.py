from __future__ import annotations

from alembic import op

revision = "20260520_0005"
down_revision = "20260516_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("update channels set provider = 'onchain' where provider = 'bsc'")
    op.execute("update snapshot_assets set provider = 'onchain' where provider = 'bsc'")


def downgrade() -> None:
    op.execute("update channels set provider = 'bsc' where provider = 'onchain'")
    op.execute("update snapshot_assets set provider = 'bsc' where provider = 'onchain'")
