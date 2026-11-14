"""Note metadata (API contract §3.2) for search hits, assembled exactly as the note
endpoints assemble it."""

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.api import schemas
from app.api.notes import load_note_rows, note_query
from app.notes.models import File


async def load_notes(
    db: AsyncSession, file_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, schemas.Note]:
    rows = (await db.execute(note_query().where(File.file_id.in_(file_ids)))).all()
    return {note.id: note for note in await load_note_rows(db, rows)}
