"""Production sync server (Phase 5): times on operation results and conflicts, and a
revision on conflicts so resolving one follows the If-Match rule.

`client_ops.created_at` lets the retention job (P5-07) expire operation results after
the tombstone window. Existing rows get the migration's time, so they expire one window
after the upgrade, never earlier.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-14
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None

_NOW = sa.text("now()")


def upgrade() -> None:
    op.add_column(
        "client_ops",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.add_column(
        "conflicts",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.add_column("conflicts", sa.Column("resolved_at", sa.DateTime(timezone=True)))
    op.add_column(
        "conflicts", sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_index("ix_conflicts_vault_status", "conflicts", ["vault_id", "status", "id"])


def downgrade() -> None:
    op.drop_index("ix_conflicts_vault_status", table_name="conflicts")
    op.drop_column("conflicts", "revision")
    op.drop_column("conflicts", "resolved_at")
    op.drop_column("conflicts", "created_at")
    op.drop_column("client_ops", "created_at")
