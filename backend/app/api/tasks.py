"""Tasks across a vault (P6-01, P6-02) and the link graph (P6-08).

Tasks are read from the derived index; toggling one rewrites the note through the same
commit path as any note edit, based on the revision the caller saw (`If-Match`)."""

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy import func, literal, select, tuple_

from app.api.conventions import check_if_match, decode_cursor, encode_cursor, etag
from app.api.deps import DB, not_found, require_vault
from app.api.http import Cursor, IfMatch, Limit, VaultIdQuery
from app.api.notes import _bytes, _commit_at, _load, _sha, _stem
from app.api.schemas import (
    Graph,
    GraphEdge,
    GraphNode,
    Note,
    NoteRef,
    Task,
    TaskPage,
    TaskPatch,
    TaskStatusFilter,
)
from app.auth.dependencies import Principal, get_caller
from app.core.problems import ProblemError
from app.notes import graph as link_graph
from app.notes.document import parse_note
from app.notes.models import File
from app.notes.models import Note as NoteRow
from app.sync.commit import Update
from app.tasks.models import TaskRow
from app.tasks.parse import complete, extract_tasks

router = APIRouter(prefix="/api/v1", tags=["tasks"])
Caller = Annotated[Principal, Depends(get_caller)]

_ETAG = {
    "ETag": {"description": 'The note\'s revision, `"<revision>"`', "schema": {"type": "string"}}
}
_NO_DUE = dt.date.max  # open-ended tasks sort after every dated one


@router.get("/tasks")
async def list_tasks(
    caller: Caller,
    db: DB,
    vault_id: VaultIdQuery,
    status: TaskStatusFilter = "open",
    note_id: Annotated[uuid.UUID | None, Query(description="Only this note's tasks")] = None,
    due_before: Annotated[
        dt.date | None, Query(description="Only tasks due on or before this date")
    ] = None,
    cursor: Cursor = None,
    limit: Limit = 100,
) -> TaskPage:
    """Tasks by due date (undated last), then note path and position in the note."""
    await require_vault(db, caller, vault_id, "viewer")
    due = func.coalesce(TaskRow.due, _NO_DUE)
    query = (
        select(TaskRow, File.path, File.revision, NoteRow.title)
        .join(File, File.file_id == TaskRow.file_id)
        .outerjoin(NoteRow, NoteRow.file_id == TaskRow.file_id)
        .where(TaskRow.vault_id == vault_id, ~File.deleted)
    )
    if status != "any":
        query = query.where(TaskRow.done.is_(status == "done"))
    if note_id is not None:
        query = query.where(TaskRow.file_id == note_id)
    if due_before is not None:
        query = query.where(TaskRow.due <= due_before)
    if (after := decode_cursor(cursor, 4)) is not None:
        try:
            position = tuple_(
                literal(dt.date.fromisoformat(str(after[0]))),
                literal(str(after[1])).collate("C"),
                literal(uuid.UUID(str(after[2]))),
                literal(int(after[3])),
            )
        except ValueError, TypeError:
            raise ProblemError(
                400, "Invalid cursor", "invalid-cursor", "The cursor is not valid."
            ) from None
        query = query.where(
            tuple_(due, File.path.collate("C"), TaskRow.file_id, TaskRow.ordinal) > position
        )
    order = (due, File.path.collate("C"), TaskRow.file_id, TaskRow.ordinal)
    rows = (await db.execute(query.order_by(*order).limit(limit + 1))).all()
    items = [_task(*row) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last, path = rows[limit - 1][0], rows[limit - 1][1]
        next_cursor = encode_cursor([last.due or _NO_DUE, path, str(last.file_id), last.ordinal])
    return TaskPage(items=items, next_cursor=next_cursor)


def _task(row: TaskRow, path: str, revision: int, title: str | None) -> Task:
    return Task(
        note=NoteRef(id=row.file_id, path=path, title=title or _stem(path)),
        ordinal=row.ordinal,
        revision=revision,
        line=row.line,
        status=row.status,
        done=row.done,
        text=row.text,
        parent=row.parent,
        due=row.due,
        scheduled=row.scheduled,
        start=row.start,
        done_on=row.done_on,
        priority=row.priority,
        recurrence=row.recurrence,
    )


@router.patch("/notes/{note_id}/tasks/{ordinal}", responses={200: {"headers": _ETAG}})
async def update_task(
    note_id: uuid.UUID,
    ordinal: Annotated[int, Path(ge=0, le=1_000_000)],
    body: TaskPatch,
    request: Request,
    caller: Caller,
    db: DB,
    response: Response,
    if_match: IfMatch = None,
) -> Note:
    """Check or uncheck a task, based on the note revision in `If-Match`. One character
    changes; completing a recurring task also stamps it `✅` and adds the next occurrence
    above it, as the Tasks plugin does. Returns the note after the change."""
    file, vault, note = await _load(db, caller, note_id, "editor")
    check_if_match(if_match, file.revision, note.model_dump(mode="json"))
    if note.read_only:
        raise ProblemError(
            409, "Note is read-only", "note-read-only", "This note cannot be edited."
        )
    doc = parse_note(await _bytes(request, vault, file.content_hash))
    tasks = extract_tasks(doc)
    if not 0 <= ordinal < len(tasks):
        raise not_found("Task")
    task = tasks[ordinal]
    if task.done != body.done:
        data = complete(doc, task, body.today or dt.datetime.now(dt.UTC).date())
        op = Update(uuid.uuid7(), file.file_id, file.revision, _sha(data))
        note = await _commit_at(request, db, caller, vault, op, data)
    response.headers["ETag"] = etag(note.revision)
    return note


@router.get("/graph", tags=["notes"])
async def get_graph(
    caller: Caller,
    db: DB,
    vault_id: VaultIdQuery,
    attachments: Annotated[bool, Query(description="Include linked attachments")] = False,
    unresolved: Annotated[bool, Query(description="Include unresolved link targets")] = False,
    center: Annotated[
        uuid.UUID | None, Query(description="Local graph around this note instead")
    ] = None,
    depth: Annotated[int, Query(ge=1, le=5, description="Links from `center`")] = 1,
) -> Graph:
    """The vault's link graph, as Obsidian's graph view draws it: every note (orphans
    too), edges counted per linking note and target, links to itself left out."""
    await require_vault(db, caller, vault_id, "viewer")
    result = await db.run_sync(
        lambda s: link_graph.graph(
            s,
            vault_id,
            attachments=attachments,
            unresolved=unresolved,
            center=center,
            depth=depth,
        )
    )
    return Graph(
        nodes=[GraphNode(id=n.id, kind=n.kind, label=n.label, path=n.path) for n in result.nodes],
        edges=[GraphEdge(source=e.source, target=e.target, count=e.count) for e in result.edges],
    )
