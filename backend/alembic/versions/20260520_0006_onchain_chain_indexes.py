from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "20260520_0006"
down_revision = "20260520_0005"
branch_labels = None
depends_on = None

DEFAULT_CHAIN_INDEXES = ["1", "56"]


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("select id, public_config_json from channels where provider = 'onchain'")
    ).mappings()
    for row in rows:
        try:
            config = json.loads(row["public_config_json"] or "{}")
        except json.JSONDecodeError:
            config = {}
        if config.get("chainIndexes"):
            continue
        config["chainIndexes"] = DEFAULT_CHAIN_INDEXES
        connection.execute(
            sa.text("update channels set public_config_json = :config where id = :id"),
            {"config": json.dumps(config), "id": row["id"]},
        )


def downgrade() -> None:
    pass
