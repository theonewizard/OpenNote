"""Full-text search documents (Phase 2 Task 7, API contract §5).

One row per indexed note: title, aliases and tags, and the body without frontmatter, with
a generated `tsvector` (title weight A, aliases and tags B, body C, `simple` config) and
trigram indexes for partial words. The rows are derived like `notes`: `index_file` writes
them, so notes indexed before this migration are found once the index is rebuilt
(`app.notes.index.rebuild_index`); the migration cannot fill them, it has no note bytes.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None

TSV = (
    "setweight(to_tsvector('simple'::regconfig, title), 'A') || "
    "setweight(to_tsvector('simple'::regconfig, keywords), 'B') || "
    "setweight(to_tsvector('simple'::regconfig, body), 'C')"
)


def upgrade() -> None:
    op.create_table(
        "search_documents",
        sa.Column(
            "file_id",
            sa.Uuid(),
            sa.ForeignKey("files.file_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "vault_id", sa.Uuid(), sa.ForeignKey("vaults.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("keywords", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("tsv", TSVECTOR(), sa.Computed(TSV, persisted=True), nullable=False),
    )
    op.create_index("search_documents_vault", "search_documents", ["vault_id"])
    op.create_index("search_documents_tsv", "search_documents", ["tsv"], postgresql_using="gin")
    for column in ("title", "body"):
        op.create_index(
            f"search_documents_{column}_trgm",
            "search_documents",
            [column],
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )


def downgrade() -> None:
    op.drop_table("search_documents")
