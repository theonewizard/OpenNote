"""Record the revision each file last had written to the vault (sync protocol §2.3).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # NULL for existing rows: recovery then falls back to the previous revision as before.
    op.add_column("files", sa.Column("written_revision", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("files", "written_revision")
