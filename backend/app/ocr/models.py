"""Text read from image and PDF attachments (migration 0011). Keyed by vault and content
hash, so a renamed or copied attachment is not read again; rows whose hash no live
attachment in the vault has any more are removed by the next OCR run."""

import uuid

from sqlalchemy import Computed, ForeignKey
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class OcrText(Base):
    __tablename__ = "ocr_texts"

    vault_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vaults.id", ondelete="CASCADE"), primary_key=True
    )
    content_hash: Mapped[str] = mapped_column(primary_key=True)
    text: Mapped[str]
    failed: Mapped[bool]  # unreadable: kept so that it is not tried again
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple'::regconfig, text)", persisted=True)
    )
