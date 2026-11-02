"""File identity registry and the derived note index.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def _file_fk(**kwargs: str) -> sa.Column:
    return sa.Column(
        "file_id", sa.Uuid(), sa.ForeignKey("files.file_id", ondelete="CASCADE"), **kwargs
    )


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("file_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "vault_id", sa.Uuid(), sa.ForeignKey("vaults.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("path_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "uq_files_live_path",
        "files",
        ["vault_id", "path_key"],
        unique=True,
        postgresql_where=sa.text("NOT deleted"),
    )
    op.create_table(
        "notes",
        _file_fk(primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("properties", JSONB(), nullable=True),
        sa.Column("frontmatter_error", sa.Boolean(), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "note_tags",
        _file_fk(primary_key=True),
        sa.Column("tag_key", sa.Text(), primary_key=True),
        sa.Column("tag", sa.Text(), nullable=False),
    )
    op.create_index("ix_note_tags_tag_key", "note_tags", ["tag_key"])
    op.create_table(
        "note_links",
        _file_fk(primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column(
            "resolved_file_id",
            sa.Uuid(),
            sa.ForeignKey("files.file_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("embed", sa.Boolean(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=True),
        sa.Column("block", sa.Text(), nullable=True),
        sa.Column("alias", sa.Text(), nullable=True),
    )
    op.create_index("ix_note_links_resolved", "note_links", ["resolved_file_id"])


def downgrade() -> None:
    op.drop_table("note_links")
    op.drop_table("note_tags")
    op.drop_table("notes")
    op.drop_table("files")
