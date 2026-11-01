"""Sync state: per-vault change sequence, revisions, operation results, conflicts.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def _vault_fk(**kwargs: bool) -> sa.Column:
    return sa.Column(
        "vault_id", sa.Uuid(), sa.ForeignKey("vaults.id", ondelete="CASCADE"), **kwargs
    )


def upgrade() -> None:
    op.create_table(
        "vault_seq",
        _vault_fk(primary_key=True),
        sa.Column("last_seq", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_table(
        "revisions",
        _vault_fk(primary_key=True),
        sa.Column("seq", sa.BigInteger(), primary_key=True),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column("op", sa.Text(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("file_id", "revision"),
    )
    op.create_table(
        "client_ops",
        _vault_fk(primary_key=True),
        sa.Column("client_op_id", sa.Uuid(), primary_key=True),
        sa.Column("result", JSONB(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=True),
    )
    op.create_table(
        "conflicts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _vault_fk(nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("copy_file_id", sa.Uuid(), nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("their_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
    )


def downgrade() -> None:
    op.drop_table("conflicts")
    op.drop_table("client_ops")
    op.drop_table("revisions")
    op.drop_table("vault_seq")
