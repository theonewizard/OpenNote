"""Text read from image and PDF attachments (P6-06): Tesseract for scans, a PDF's own text
layer where it has one. Filled by the worker's OCR job; searched with the notes that
link to the attachment.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "ocr_texts",
        sa.Column(
            "vault_id", sa.Uuid(), sa.ForeignKey("vaults.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("content_hash", sa.Text(), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("failed", sa.Boolean(), nullable=False),
        sa.Column(
            "tsv",
            TSVECTOR(),
            sa.Computed("to_tsvector('simple'::regconfig, text)", persisted=True),
            nullable=False,
        ),
    )
    op.create_index("ocr_texts_tsv", "ocr_texts", ["tsv"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_table("ocr_texts")
