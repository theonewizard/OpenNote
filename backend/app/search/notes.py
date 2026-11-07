"""Note metadata (API contract §3.2) for a set of file ids, as search hits carry it.

Assembled from `files`, `notes`, `note_tags` and `revisions`, the way the notes endpoints
assemble it; the two can share one helper once both are merged.
"""

import datetime as dt
import uuid
from collections.abc import Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api import schemas
from app.notes.models import File, Note, NoteTag
from app.sync.models import Revision
from app.vaults.paths import validate

_EPOCH = dt.datetime.fromtimestamp(0, dt.UTC)  # a note indexed without any revision


async def load_notes(
    db: AsyncSession, file_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, schemas.Note]:
    first, current = aliased(Revision), aliased(Revision)
    rows = await db.execute(
        select(File, Note, first.committed_at, current.committed_at, current.device_id)
        .join(Note, Note.file_id == File.file_id)
        .outerjoin(first, and_(first.file_id == File.file_id, first.revision == 1))
        .outerjoin(
            current, and_(current.file_id == File.file_id, current.revision == File.revision)
        )
        .where(File.file_id.in_(file_ids))
    )
    tags: dict[uuid.UUID, list[str]] = {}
    for file_id, tag in await db.execute(
        select(NoteTag.file_id, NoteTag.tag)
        .where(NoteTag.file_id.in_(file_ids))
        .order_by(NoteTag.tag)
    ):
        tags.setdefault(file_id, []).append(tag)
    notes = {}
    for file, note, created, modified, device in rows.all():
        props = note.properties
        violations = validate(file.path, note=True)
        notes[file.file_id] = schemas.Note(
            id=file.file_id,
            vault_id=file.vault_id,
            path=file.path,
            title=note.title,
            revision=file.revision,
            content_hash=file.content_hash,
            size=file.size,
            created_at=created or modified or _EPOCH,
            modified_at=modified or created or _EPOCH,
            modified_by_device=device or "unknown",
            tags=tags.get(file.file_id, []),
            aliases=[a for a in (props or {}).get("aliases") or [] if isinstance(a, str)],
            properties=props,
            frontmatter_error=note.frontmatter_error,
            read_only=note.read_only,
            path_warning=violations[0].code if violations else None,
            has_id_in_file=str((props or {}).get("id", "")).lower() == str(file.file_id),
        )
    return notes
