"""Optional AI: per-vault opt-in and note embeddings (ADR-0016, P7-01, P7-02).

The vector column has no fixed dimension because the dimension is the embedding
model's; the similarity index arrives with semantic search (P7-03).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-07
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def _file_fk(**kwargs: bool) -> sa.Column:
    return sa.Column(
        "file_id", sa.Uuid(), sa.ForeignKey("files.file_id", ondelete="CASCADE"), **kwargs
    )


def upgrade() -> None:
    op.create_table(
        "ai_vault_settings",
        sa.Column(
            "vault_id", sa.Uuid(), sa.ForeignKey("vaults.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allow_external", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "ai_note_state",
        _file_fk(primary_key=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
    )
    op.create_table(
        "ai_chunks",
        _file_fk(primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("text_hash", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    # SQLAlchemy has no pgvector type; 0001 created the extension.
    op.execute("ALTER TABLE ai_chunks ADD COLUMN embedding vector NOT NULL")


def downgrade() -> None:
    op.drop_table("ai_chunks")
    op.drop_table("ai_note_state")
    op.drop_table("ai_vault_settings")
