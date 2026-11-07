"""Note endpoints on the sync commit path (P2-04). Bytes go in and out unchanged: the
content endpoints speak `text/markdown`, and the server never reformats a note."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.http import Cursor, IdempotencyKey, IfMatch, Limit, VaultIdQuery, not_implemented
from app.api.schemas import Note, NoteCreate, NoteLinks, NotePage, NotePatch, NoteSort
from app.auth.dependencies import Principal, get_caller

router = APIRouter(prefix="/api/v1/notes", tags=["notes"])
Caller = Annotated[Principal, Depends(get_caller)]

_ETAG = {"ETag": {"description": 'The revision, `"<revision>"`', "schema": {"type": "string"}}}
_MARKDOWN = {"text/markdown": {"schema": {"type": "string"}}}


@router.get("")
async def list_notes(
    caller: Caller,
    vault_id: VaultIdQuery,
    folder: Annotated[
        str | None, Query(max_length=1024, description="Only notes directly in this folder")
    ] = None,
    tag: Annotated[
        str | None, Query(max_length=255, description="Only notes with this tag or a child tag")
    ] = None,
    sort: NoteSort = "path",
    cursor: Cursor = None,
    limit: Limit = 50,
) -> NotePage:
    raise not_implemented()


@router.post("", status_code=201, responses={201: {"headers": _ETAG}})
async def create_note(
    body: NoteCreate, caller: Caller, idempotency_key: IdempotencyKey = None
) -> Note:
    """Create a note. A note OpenNote creates gets an `id` in its frontmatter."""
    raise not_implemented()


@router.get("/{note_id}", responses={200: {"headers": _ETAG}})
async def get_note(note_id: uuid.UUID, caller: Caller) -> Note:
    raise not_implemented()


@router.patch("/{note_id}", responses={200: {"headers": _ETAG}})
async def update_note(
    note_id: uuid.UUID, body: NotePatch, caller: Caller, if_match: IfMatch = None
) -> Note:
    """Move or rename (`path`), or edit `tags`, `aliases` and the `opennote:` namespace
    with the round-trip frontmatter editor, which keeps every other byte."""
    raise not_implemented()


@router.delete("/{note_id}", status_code=204)
async def delete_note(note_id: uuid.UUID, caller: Caller, if_match: IfMatch = None) -> None:
    """Delete: the file moves to the recovery area and a tombstone revision is kept."""
    raise not_implemented()


@router.get(
    "/{note_id}/content",
    response_class=Response,
    responses={200: {"content": _MARKDOWN, "headers": _ETAG}},
)
async def get_note_content(note_id: uuid.UUID, caller: Caller) -> Response:
    """The note's exact bytes."""
    raise not_implemented()


@router.put(
    "/{note_id}/content",
    responses={200: {"headers": _ETAG}},
    openapi_extra={"requestBody": {"required": True, "content": _MARKDOWN}},
)
async def put_note_content(
    note_id: uuid.UUID, request: Request, caller: Caller, if_match: IfMatch = None
) -> Note:
    """Replace the note's bytes (`text/markdown`, at most 16 MiB). A stale `If-Match` is
    a 412 carrying the current note; clients wanting a merge use sync push (Phase 5)."""
    raise not_implemented()


@router.get("/{note_id}/links")
async def get_note_links(note_id: uuid.UUID, caller: Caller) -> NoteLinks:
    """Outgoing links, backlinks and unresolved targets."""
    raise not_implemented()
