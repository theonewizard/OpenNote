"""ORM models for the file identity registry and the derived note index (migration 0003).

`files` is identity and is never dropped by a rebuild; `notes`, `note_tags` and
`note_links` are derived from the vault and can be rebuilt at any time.
"""

import uuid
from typing import Any

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class File(Base):
    __tablename__ = "files"

    file_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    vault_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vaults.id", ondelete="CASCADE"))
    path: Mapped[str]
    path_key: Mapped[str]  # casefold_key(path): the unique key among live files
    kind: Mapped[str]
    size: Mapped[int] = mapped_column(BigInteger)
    content_hash: Mapped[str]
    revision: Mapped[int] = mapped_column(default=0)
    deleted: Mapped[bool] = mapped_column(default=False)


class Note(Base):
    __tablename__ = "notes"

    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.file_id", ondelete="CASCADE"), primary_key=True
    )
    title: Mapped[str]
    properties: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    frontmatter_error: Mapped[bool]
    read_only: Mapped[bool]


class NoteTag(Base):
    __tablename__ = "note_tags"

    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.file_id", ondelete="CASCADE"), primary_key=True
    )
    tag_key: Mapped[str] = mapped_column(primary_key=True)
    tag: Mapped[str]


class NoteLink(Base):
    __tablename__ = "note_links"

    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.file_id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    target: Mapped[str]
    resolved_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("files.file_id", ondelete="SET NULL")
    )
    embed: Mapped[bool]
    heading: Mapped[str | None]
    block: Mapped[str | None]
    alias: Mapped[str | None]
