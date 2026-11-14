"""ORM models for the AI tables (migration 0008). Everything but ai_vault_settings is
derived from the vault and can be dropped and rebuilt."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.core.db import Base


class Vector(UserDefinedType[list[float]]):
    """pgvector's `vector`, without a fixed dimension: the dimension is the model's.
    Values travel as pgvector's text form, '[1,2,3]'."""

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "vector"

    def bind_expression(self, bindvalue: Any) -> Any:
        return func.cast(bindvalue, self)

    def bind_processor(self, dialect: Any) -> Any:
        def process(value: list[float] | None) -> str | None:
            return None if value is None else "[" + ",".join(map(repr, value)) + "]"

        return process

    def result_processor(self, dialect: Any, coltype: Any) -> Any:
        def process(value: str | None) -> list[float] | None:
            return None if value is None else [float(x) for x in value.strip("[]").split(",")]

        return process


class AIVaultSettings(Base):
    """Per-vault opt-in, kept in the database and not in the vault, so a synced or copied
    vault cannot switch AI on, or allow an external provider, by itself."""

    __tablename__ = "ai_vault_settings"

    vault_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vaults.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(default=False)
    allow_external: Mapped[bool] = mapped_column(default=False)


class AINoteState(Base):
    """Which file content and model a note's chunks were embedded from."""

    __tablename__ = "ai_note_state"

    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.file_id", ondelete="CASCADE"), primary_key=True
    )
    content_hash: Mapped[str]
    model: Mapped[str]


class AIChunk(Base):
    __tablename__ = "ai_chunks"

    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.file_id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    text_hash: Mapped[str]  # of the embedded text, so unchanged chunks keep their vector
    text: Mapped[str]
    embedding: Mapped[list[float]] = mapped_column(Vector())
