"""Retention horizon per vault (P5-07): the newest seq whose tombstone retention has
removed. A pull cursor older than it is answered 410, so the client reconciles from a
snapshot instead of missing a delete.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-14
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "vault_seq",
        sa.Column("horizon_seq", sa.BigInteger(), nullable=False, server_default="0"),
    )
    # The retention job selects a vault's old revisions by time.
    op.create_index("ix_revisions_vault_committed", "revisions", ["vault_id", "committed_at"])


def downgrade() -> None:
    op.drop_index("ix_revisions_vault_committed", table_name="revisions")
    op.drop_column("vault_seq", "horizon_seq")
