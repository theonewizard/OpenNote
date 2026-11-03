"""ORM model for registered vaults (migration 0002)."""

import uuid

from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Vault(Base):
    __tablename__ = "vaults"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str]
    root_path: Mapped[str] = mapped_column(unique=True)
