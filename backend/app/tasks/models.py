"""The derived task index (migration 0008): one row per task in a live note, written with
the other derived rows by `app.notes.index` and rebuildable from the vault."""

import datetime as dt
import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class TaskRow(Base):
    __tablename__ = "tasks"

    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.file_id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(primary_key=True)  # position among the note's tasks
    vault_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vaults.id", ondelete="CASCADE"))
    line: Mapped[int]
    status: Mapped[str]
    done: Mapped[bool]
    text: Mapped[str]
    parent: Mapped[int | None]
    due: Mapped[dt.date | None]
    scheduled: Mapped[dt.date | None]
    start: Mapped[dt.date | None]
    done_on: Mapped[dt.date | None]
    priority: Mapped[str | None]
    recurrence: Mapped[str | None]
