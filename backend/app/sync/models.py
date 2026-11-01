"""ORM models for sync state (migration 0004, sync protocol §2.1)."""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class VaultSeq(Base):
    """One row per vault; locked FOR UPDATE by every commit, which serializes them."""

    __tablename__ = "vault_seq"

    vault_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vaults.id", ondelete="CASCADE"), primary_key=True
    )
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0)


class Revision(Base):
    __tablename__ = "revisions"
    __table_args__ = (UniqueConstraint("file_id", "revision"),)

    vault_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vaults.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_id: Mapped[uuid.UUID]
    revision: Mapped[int]
    path: Mapped[str]
    kind: Mapped[str]
    content_hash: Mapped[str | None]
    size: Mapped[int] = mapped_column(BigInteger)
    deleted: Mapped[bool]
    device_id: Mapped[str]
    op: Mapped[str]
    committed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class ClientOp(Base):
    """The stored result of every processed operation, for idempotent retries (I4)."""

    __tablename__ = "client_ops"

    vault_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vaults.id", ondelete="CASCADE"), primary_key=True
    )
    client_op_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    seq: Mapped[int | None] = mapped_column(BigInteger)


class Conflict(Base):
    __tablename__ = "conflicts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    vault_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vaults.id", ondelete="CASCADE"))
    file_id: Mapped[uuid.UUID]
    copy_file_id: Mapped[uuid.UUID]
    base_revision: Mapped[int]
    their_revision: Mapped[int]
    status: Mapped[str] = mapped_column(default="open")
