"""Calendar feed tokens (P6-03): a read-only iCalendar subscription of a vault's dated
tasks. Revoking a feed deletes its row.

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
    op.create_table(
        "calendar_feeds",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "vault_id", sa.Uuid(), sa.ForeignKey("vaults.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("calendar_feeds_user", "calendar_feeds", ["user_id"])


def downgrade() -> None:
    op.drop_table("calendar_feeds")
