"""The derived task index (P6-01, P6-02).

One row per task (`- [ ]` list item) in a live note, with the Tasks plugin's dates,
priority and recurrence rule, and the Reminder plugin's reminder (local wall-clock time).
Derived like `notes`: `index_file` writes the rows, so tasks
in notes indexed before this migration appear once the index is rebuilt
(`app.notes.index.rebuild_index`).

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


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column(
            "file_id", sa.Uuid(), sa.ForeignKey("files.file_id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "vault_id", sa.Uuid(), sa.ForeignKey("vaults.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("line", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("parent", sa.Integer(), nullable=True),
        sa.Column("due", sa.Date(), nullable=True),
        sa.Column("scheduled", sa.Date(), nullable=True),
        sa.Column("start", sa.Date(), nullable=True),
        sa.Column("done_on", sa.Date(), nullable=True),
        sa.Column("priority", sa.Text(), nullable=True),
        sa.Column("recurrence", sa.Text(), nullable=True),
        sa.Column("remind_at", sa.DateTime(timezone=False), nullable=True),
        sa.PrimaryKeyConstraint("file_id", "ordinal"),
    )
    op.create_index("tasks_vault_done_due", "tasks", ["vault_id", "done", "due"])
    op.create_index(
        "tasks_vault_remind_at",
        "tasks",
        ["vault_id", "remind_at"],
        postgresql_where=sa.text("remind_at IS NOT NULL AND NOT done"),
    )


def downgrade() -> None:
    op.drop_table("tasks")
