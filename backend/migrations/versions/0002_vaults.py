"""Registered vaults.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-01
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "vaults",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=False, unique=True),
    )


def downgrade() -> None:
    op.drop_table("vaults")
