"""ORM models for registered vaults (migration 0002, metadata from 0006) and members."""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Vault(Base):
    __tablename__ = "vaults"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str]
    root_path: Mapped[str] = mapped_column(unique=True)
    revision: Mapped[int] = mapped_column(default=1, server_default="1")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class VaultMember(Base):
    __tablename__ = "vault_members"

    vault_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vaults.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str]
