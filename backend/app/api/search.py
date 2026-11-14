"""Tags (P2-07) and search (P2-08). Both are scoped to the caller's vaults before matching."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by

from app.api.conventions import decode_cursor, encode_cursor
from app.api.deps import DB, require_vault
from app.api.http import Cursor, Limit, VaultIdQuery
from app.api.schemas import SearchHit, SearchPage, Tag, TagPage
from app.auth.dependencies import Principal, get_caller
from app.core.problems import ProblemError
from app.notes.models import File, NoteTag
from app.search.grammar import parse
from app.search.notes import load_notes
from app.search.query import run_search
from app.vaults.models import Vault, VaultMember

router = APIRouter(prefix="/api/v1", tags=["search"])
Caller = Annotated[Principal, Depends(get_caller)]


@router.get("/tags")
async def list_tags(
    caller: Caller, db: DB, vault_id: VaultIdQuery, cursor: Cursor = None, limit: Limit = 500
) -> TagPage:
    """Tags with their note counts, sorted by name."""
    await require_vault(db, caller, vault_id, "viewer")
    after = decode_cursor(cursor, 1)
    if after is not None and not isinstance(after[0], str):
        raise _bad_cursor()
    # One row per spelling of a tag; a note holds each tag (by key) at most once.
    spellings = (
        select(NoteTag.tag_key, NoteTag.tag, func.count().label("notes"))
        .join(File, File.file_id == NoteTag.file_id)
        .where(File.vault_id == vault_id, ~File.deleted)
        .group_by(NoteTag.tag_key, NoteTag.tag)
        .subquery()
    )
    key = spellings.c.tag_key.collate("C")
    most_common = func.array_agg(
        aggregate_order_by(spellings.c.tag, spellings.c.notes.desc(), spellings.c.tag.collate("C"))
    )[1]
    query = select(key, most_common, func.sum(spellings.c.notes)).group_by(key).order_by(key)
    if after is not None:
        query = query.where(key > after[0])
    rows = (await db.execute(query.limit(limit + 1))).all()
    items = [Tag(name=name, count=count) for _, name, count in rows[:limit]]
    next_cursor = encode_cursor([rows[limit - 1][0]]) if len(rows) > limit else None
    return TagPage(items=items, next_cursor=next_cursor)


def _bad_cursor() -> ProblemError:
    return ProblemError(400, "Invalid cursor", "invalid-cursor", "The cursor is not valid.")


def _caller_vaults(caller: Principal) -> Select[uuid.UUID]:
    """The live vaults the caller is a member of, within a token's vaults."""
    query = (
        select(VaultMember.vault_id)
        .join(Vault, Vault.id == VaultMember.vault_id)
        .where(VaultMember.user_id == caller.user_id, Vault.deleted_at.is_(None))
    )
    if caller.pat_vaults is not None:
        query = query.where(VaultMember.vault_id.in_(caller.pat_vaults))
    return query


def _after(cursor: str | None) -> tuple[float, uuid.UUID] | None:
    values: list[Any] | None = decode_cursor(cursor, 2)
    if values is None:
        return None
    score, file_id = values
    try:
        if isinstance(score, bool) or not isinstance(score, int | float):
            raise ValueError
        return float(score), uuid.UUID(str(file_id))
    except ValueError:
        raise _bad_cursor() from None


@router.get("/search")
async def search(
    caller: Caller,
    db: DB,
    q: Annotated[str, Query(max_length=1024, description="Query, grammar in API contract §5")],
    vault_id: Annotated[
        uuid.UUID | None, Query(description="One vault; omitted, every vault of the caller")
    ] = None,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> SearchPage:
    """Full-text search with filters, best match first."""
    after = _after(cursor)
    scope: Select[uuid.UUID] | uuid.UUID
    if vault_id is not None:
        await require_vault(db, caller, vault_id, "viewer")
        scope = vault_id
    else:
        scope = _caller_vaults(caller)
    tree = parse(q)
    if tree is None or caller.user_id is None:
        return SearchPage(items=[], next_cursor=None)
    hits, more = await run_search(db, scope, tree, after, limit)
    notes = await load_notes(db, [hit.file_id for hit in hits])
    items = [
        SearchHit(note=notes[hit.file_id], snippet=hit.snippet, score=hit.score)
        for hit in hits
        if hit.file_id in notes
    ]
    next_cursor = encode_cursor([hits[-1].score, str(hits[-1].file_id)]) if more else None
    return SearchPage(items=items, next_cursor=next_cursor)
