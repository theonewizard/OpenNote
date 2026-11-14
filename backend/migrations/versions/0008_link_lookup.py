"""Indexes that let a commit re-resolve only the links its file can change (P8-01).

Before this, every indexed note re-resolved every unresolved link of its vault against
every path, which never finished importing a 100k-note vault. Now a link carries
`target_key`, the case-folded file name its target names, and `files` has an index on
the case-folded file name of each path, so the links a file can satisfy and the files a
link can name are both index lookups.

`target_key` is computed in Python (`app.notes.links.target_key`: NFC plus Unicode case
folding, which SQL `lower()` does not match), so the migration cannot fill it. Links
indexed before it keep NULL and are re-resolved on every commit, as before, until their
note is indexed again or the index is rebuilt (`app.notes.index.rebuild_index`).

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

LEAF = "regexp_replace(path_key, '^.*/', '')"


def upgrade() -> None:
    op.add_column("note_links", sa.Column("target_key", sa.Text(), nullable=True))
    op.create_index("note_links_target_key", "note_links", ["target_key"])
    op.create_index("note_links_resolved", "note_links", ["resolved_file_id"])
    op.create_index("files_leaf", "files", ["vault_id", sa.text(LEAF)])


def downgrade() -> None:
    op.drop_index("files_leaf", table_name="files")
    op.drop_index("note_links_resolved", table_name="note_links")
    op.drop_index("note_links_target_key", table_name="note_links")
    op.drop_column("note_links", "target_key")
