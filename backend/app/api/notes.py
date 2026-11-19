"""Note endpoints on the sync commit path (P2-04). Bytes go in and out unchanged: the
content endpoints speak `text/markdown`, and the server never reformats a note."""

import datetime as dt
import hashlib
import posixpath
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any

import anyio.to_thread
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Select, exists, func, literal, or_, select, tuple_
from sqlalchemy.orm import aliased

from app.api.conventions import (
    check_if_match,
    decode_cursor,
    encode_cursor,
    etag,
    remember,
    replay,
    request_hash,
)
from app.api.deps import DB, StaleRevision, commit, not_found, require_vault
from app.api.http import Cursor, IdempotencyKey, IfMatch, Limit, VaultIdQuery
from app.api.schemas import (
    Note,
    NoteCreate,
    NoteLinks,
    NotePage,
    NotePatch,
    NoteRef,
    NoteSort,
    OutgoingLink,
    Role,
)
from app.auth.dependencies import Principal, get_caller
from app.core.audit import audit
from app.core.problems import PROBLEM_TYPE_BASE, ProblemError
from app.notes.document import parse_note
from app.notes.frontmatter import (
    DELETE,
    FrontmatterInvalid,
    edit_properties,
    load_frontmatter,
    splice_keys,
)
from app.notes.models import File, NoteLink, NoteTag
from app.notes.models import Note as NoteRow
from app.notes.templates import render
from app.sync.commit import Create, Delete, Move, Operation, OpResult, Update
from app.sync.history import HistoryStore
from app.sync.models import ClientOp, Revision
from app.vaults.models import Vault
from app.vaults.paths import casefold_key, classify, normalize, validate
from app.vaults.scan import MAX_NOTE_BYTES

router = APIRouter(prefix="/api/v1/notes", tags=["notes"])
Caller = Annotated[Principal, Depends(get_caller)]

_ETAG = {"ETag": {"description": 'The revision, `"<revision>"`', "schema": {"type": "string"}}}
_MARKDOWN = {"text/markdown": {"schema": {"type": "string"}}}
_OP_NAMESPACE = uuid.UUID("0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c")  # Idempotency-Key -> op id

_first = aliased(Revision)
_current = aliased(Revision)
_SORT_KEYS: dict[str, Any] = {
    "path": File.path,
    "title": func.coalesce(NoteRow.title, File.path),
    "created_at": _first.committed_at,
    "modified_at": _current.committed_at,
}

# Problems ---------------------------------------------------------------------------------


def _invalid_path() -> ProblemError:
    return ProblemError(
        422, "Invalid path", "invalid-path", "The path breaks the vault's path rules."
    )


def _path_taken() -> ProblemError:
    return ProblemError(409, "Path taken", "path-taken", "A file already exists at this path.")


def _too_large() -> ProblemError:
    return ProblemError(
        413, "Content too large", "content-too-large", "Note content is limited to 16 MiB."
    )


def _stale(note: Note) -> ProblemError:
    return ProblemError(
        412,
        "Precondition failed",
        "precondition-failed",
        "The resource has changed; its current state is in `current`.",
        extensions={"current": note.model_dump(mode="json")},
        headers={"ETag": etag(note.revision)},
    )


def refused(result: OpResult) -> ProblemError:
    """The problem of an operation the commit path rejected."""
    problem = result.problem or {}
    slug = str(problem.get("type", "")).removeprefix(PROBLEM_TYPE_BASE) or "conflict"
    return ProblemError(
        int(problem.get("status", 409)),
        str(problem.get("title", "Conflict")),
        slug,
        "The change was refused.",
    )


def ok(result: OpResult) -> bool:
    return result.status in ("applied", "merged", "duplicate")


# Reading ----------------------------------------------------------------------------------


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _stem(path: str) -> str:
    return posixpath.basename(path).rsplit(".", 1)[0]


def note_query() -> Select[File, NoteRow, dt.datetime, dt.datetime, str]:
    """Live notes with their index row and first and current revision."""
    return (
        select(File, NoteRow, _first.committed_at, _current.committed_at, _current.device_id)
        .outerjoin(NoteRow, NoteRow.file_id == File.file_id)
        .join(_first, (_first.file_id == File.file_id) & (_first.revision == 1))
        .join(_current, (_current.file_id == File.file_id) & (_current.revision == File.revision))
        .where(File.kind == "note", ~File.deleted)
        .execution_options(populate_existing=True)  # rows change in the commit threads
    )


def _note(row: Sequence[Any], tags: list[str]) -> Note:
    file, meta, created, modified, device = row[:5]
    props = meta.properties if meta else None
    aliases = props.get("aliases") if props else None
    violations = validate(file.path, note=True)
    return Note(
        id=file.file_id,
        vault_id=file.vault_id,
        path=file.path,
        title=meta.title if meta else _stem(file.path),
        revision=file.revision,
        content_hash=file.content_hash,
        size=file.size,
        created_at=created,
        modified_at=modified,
        modified_by_device=device,
        tags=tags,
        aliases=[a for a in aliases if isinstance(a, str)] if isinstance(aliases, list) else [],
        properties=props,
        frontmatter_error=meta.frontmatter_error if meta else False,
        read_only=(meta.read_only if meta else False) or file.size > MAX_NOTE_BYTES,
        path_warning=violations[0].code if violations else None,
        has_id_in_file=props is not None and "id" in props,
    )


async def load_note_rows(db: DB, rows: Sequence[Sequence[Any]]) -> list[Note]:
    tags: dict[uuid.UUID, list[str]] = {}
    ids = [row[0].file_id for row in rows]
    if ids:
        found = await db.execute(
            select(NoteTag.file_id, NoteTag.tag)
            .where(NoteTag.file_id.in_(ids))
            .order_by(NoteTag.tag_key)
        )
        for file_id, tag in found:
            tags.setdefault(file_id, []).append(tag)
    return [_note(row, tags.get(row[0].file_id, [])) for row in rows]


async def _load(
    db: DB, principal: Principal, note_id: uuid.UUID, min_role: Role
) -> tuple[File, Vault, Note]:
    """The note, its vault and its metadata; 404 for a note the caller cannot see."""
    row = (await db.execute(note_query().where(File.file_id == note_id))).first()
    if row is None:
        raise not_found("Note")
    try:
        vault, _ = await require_vault(db, principal, row[0].vault_id, min_role)
    except ProblemError as err:
        if err.status_code == 404:
            raise not_found("Note") from None
        raise
    return row[0], vault, (await load_note_rows(db, [row]))[0]


async def _bytes(request: Request, vault: Vault, content_hash: str) -> bytes:
    history = HistoryStore(Path(request.app.state.settings.history_root), vault.id)
    return await anyio.to_thread.run_sync(history.get, content_hash)


async def live_file_at(db: DB, vault_id: uuid.UUID, path: str) -> uuid.UUID | None:
    """The live file at `path`, compared case-insensitively as the vault does."""
    return await db.scalar(
        select(File.file_id).where(
            File.vault_id == vault_id, File.path_key == casefold_key(path), ~File.deleted
        )
    )


def _note_path(path: str) -> str:
    path = normalize(path)
    if classify(path) != "note" or validate(path, note=True):
        raise _invalid_path()
    return path


# Writing ----------------------------------------------------------------------------------


async def _commit_at(
    request: Request, db: DB, caller: Principal, vault: Vault, op: Operation, blob: bytes | None
) -> Note:
    """Commit an operation based on the note's current revision and return the note
    after it; 412 with the current note when another write got there first."""
    base = getattr(op, "base_revision", None)
    try:
        result = await commit(request, vault, op, caller.device_id, blob, expected_revision=base)
    except StaleRevision:
        result = None
    if result is not None and result.status == "rejected":
        raise refused(result)
    _, _, note = await _load(db, caller, op.file_id, "viewer")
    if result is None or not ok(result):
        raise _stale(note)
    return note


async def _read_body(request: Request) -> bytes:
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_NOTE_BYTES:
        raise _too_large()
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_NOTE_BYTES:
            raise _too_large()
        chunks.append(chunk)
    return b"".join(chunks)


def _initial_content(content: str | None, file_id: uuid.UUID, *, own_id: bool = False) -> bytes:
    """A new note's bytes: the content with an `id` added to its frontmatter (D5), or
    only that frontmatter. An `id` already there and invalid YAML are left alone, except
    that `own_id` (a template's copy) replaces an `id` there with the new note's."""
    if content is None:
        return f"---\nid: {file_id}\n---\n".encode()
    try:
        doc = parse_note(content.encode("utf-8"))
    except UnicodeEncodeError:
        raise ProblemError(
            422, "Invalid content", "invalid-content", "The content is not valid text."
        ) from None
    try:
        data = load_frontmatter(doc)
    except FrontmatterInvalid:
        return doc.raw
    if data is not None and "id" in data and not own_id:
        return doc.raw
    return splice_keys(doc, {"id": str(file_id)})


async def _from_template(
    request: Request, db: DB, vault: Vault, template_id: uuid.UUID, path: str, now: dt.datetime
) -> str:
    """The template note's text with its variables filled in (R-P6-006)."""
    row = await db.get(File, template_id)
    if row is None or row.vault_id != vault.id or row.kind != "note" or row.deleted:
        raise ProblemError(
            422, "Invalid template", "invalid-template", "The template is not a note here."
        )
    if row.size > MAX_NOTE_BYTES:
        raise _too_large()
    text = parse_note(await _bytes(request, vault, row.content_hash)).text
    if text is None:
        raise ProblemError(
            422, "Invalid template", "invalid-template", "The template is not valid text."
        )
    return render(text, title=_stem(path), now=now)


# Routes -----------------------------------------------------------------------------------


@router.get("")
async def list_notes(
    caller: Caller,
    db: DB,
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
    await require_vault(db, caller, vault_id, "viewer")
    name, descending = sort.lstrip("-"), sort.startswith("-")
    key = _SORT_KEYS[name]
    query = note_query().add_columns(key).where(File.vault_id == vault_id)
    if folder is not None:
        prefix = casefold_key(folder.strip("/"))
        prefix += "/" if prefix else ""
        rest = func.substr(File.path_key, len(prefix) + 1)
        query = query.where(
            File.path_key.startswith(prefix, autoescape=True), func.strpos(rest, "/") == 0
        )
    if tag is not None:
        tag_key = casefold_key(tag.strip().lstrip("#"))
        query = query.where(
            exists().where(
                NoteTag.file_id == File.file_id,
                or_(
                    NoteTag.tag_key == tag_key,
                    NoteTag.tag_key.startswith(tag_key + "/", autoescape=True),
                ),
            )
        )
    if (after := decode_cursor(cursor, 2)) is not None:
        try:
            value: Any = str(after[0])
            if name in ("created_at", "modified_at"):
                value = dt.datetime.fromisoformat(value)
            position = tuple_(literal(value, key.type), literal(uuid.UUID(str(after[1]))))
        except ValueError:
            raise ProblemError(
                400, "Invalid cursor", "invalid-cursor", "The cursor is not valid."
            ) from None
        here = tuple_(key, File.file_id)
        query = query.where(here < position if descending else here > position)
    order = (key.desc(), File.file_id.desc()) if descending else (key, File.file_id)
    rows = (await db.execute(query.order_by(*order).limit(limit + 1))).all()
    items = await load_note_rows(db, rows[:limit])
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = encode_cursor([last[5], str(last[0].file_id)])
    return NotePage(items=items, next_cursor=next_cursor)


@router.post("", status_code=201, response_model=Note, responses={201: {"headers": _ETAG}})
async def create_note(
    body: NoteCreate,
    request: Request,
    caller: Caller,
    db: DB,
    idempotency_key: IdempotencyKey = None,
) -> Response:
    """Create a note, empty, from `content`, or from a template note. A note OpenNote
    creates gets an `id` in its frontmatter."""
    vault, _ = await require_vault(db, caller, body.vault_id, "editor")
    fingerprint = request_hash("POST", "/api/v1/notes", body.model_dump_json())
    if replayed := await replay(db, caller, idempotency_key, fingerprint):
        return replayed
    path = _note_path(body.path)
    if body.template_id is not None and body.content is not None:
        raise ProblemError(
            422,
            "Content or template",
            "content-and-template",
            "Send either `content` or `template_id`, not both.",
        )
    op_id = uuid.uuid7()
    if idempotency_key is not None:  # a retry after a lost response commits nothing twice
        op_id = uuid.uuid5(
            _OP_NAMESPACE,
            f"{caller.kind}:{caller.pat_id or caller.id}:{idempotency_key}:{fingerprint}",
        )
    retry = await db.get(ClientOp, (vault.id, op_id)) is not None
    if not retry and await live_file_at(db, vault.id, path):
        raise _path_taken()
    file_id = uuid.uuid7()
    content = body.content
    if body.template_id is not None:
        now = body.local_time or dt.datetime.now(dt.UTC)
        content = await _from_template(request, db, vault, body.template_id, path, now)
    data = _initial_content(content, file_id, own_id=body.template_id is not None)
    if len(data) > MAX_NOTE_BYTES:
        raise _too_large()
    op = Create(op_id, file_id, path, "note", _sha(data))
    result = await commit(request, vault, op, caller.device_id, data)
    if result.status == "conflict":  # another create took the path meanwhile: undo the copy
        await commit(
            request, vault, Delete(uuid.uuid7(), result.file_id, 1), caller.device_id, None
        )
        raise _path_taken()
    if not ok(result):
        raise refused(result)
    _, _, note = await _load(db, caller, result.file_id, "viewer")
    response = JSONResponse(
        note.model_dump(mode="json"),
        status_code=201,
        headers={"ETag": etag(note.revision), "Location": f"/api/v1/notes/{note.id}"},
    )
    await remember(db, caller, idempotency_key, fingerprint, response)
    return response


@router.get("/{note_id}", responses={200: {"headers": _ETAG}})
async def get_note(note_id: uuid.UUID, caller: Caller, db: DB, response: Response) -> Note:
    _, _, note = await _load(db, caller, note_id, "viewer")
    response.headers["ETag"] = etag(note.revision)
    return note


@router.patch("/{note_id}", responses={200: {"headers": _ETAG}})
async def update_note(
    note_id: uuid.UUID,
    body: NotePatch,
    request: Request,
    caller: Caller,
    db: DB,
    response: Response,
    if_match: IfMatch = None,
) -> Note:
    """Move or rename (`path`), or edit `tags`, `aliases` and the `opennote:` namespace
    with the round-trip frontmatter editor, which keeps every other byte."""
    changes: dict[str, Any] = {
        k: v for k in ("tags", "aliases", "opennote") if (v := getattr(body, k)) is not None
    }
    if body.path is not None and changes:
        raise ProblemError(
            422,
            "Move or edit",
            "patch-move-and-edit",
            "Send either `path` or metadata fields, not both.",
        )
    file, vault, note = await _load(db, caller, note_id, "editor")
    check_if_match(if_match, file.revision, note.model_dump(mode="json"))
    if body.path is not None:
        path = _note_path(body.path)
        if path != file.path:
            if (other := await live_file_at(db, vault.id, path)) and other != file.file_id:
                raise _path_taken()
            op: Operation = Move(uuid.uuid7(), file.file_id, file.revision, path)
            note = await _commit_at(request, db, caller, vault, op, None)
    elif changes:
        if note.read_only:
            raise ProblemError(
                409, "Note is read-only", "note-read-only", "This note cannot be edited."
            )
        doc = parse_note(await _bytes(request, vault, file.content_hash))
        try:
            frontmatter = load_frontmatter(doc)
        except FrontmatterInvalid:
            raise ProblemError(
                409,
                "Frontmatter invalid",
                "frontmatter-invalid",
                "The note's frontmatter does not parse; edit its content instead.",
            ) from None
        if "opennote" in changes:  # replaces the namespace: drop the keys not sent
            old, new = frontmatter.get("opennote") if frontmatter else None, changes["opennote"]
            gone = {k: DELETE for k in old if k not in new} if isinstance(old, Mapping) else {}
            changes["opennote"] = gone | new
        data = edit_properties(doc, changes)
        if data != doc.raw:
            op = Update(uuid.uuid7(), file.file_id, file.revision, _sha(data))
            note = await _commit_at(request, db, caller, vault, op, data)
    response.headers["ETag"] = etag(note.revision)
    return note


@router.delete("/{note_id}", status_code=204)
async def delete_note(
    note_id: uuid.UUID, request: Request, caller: Caller, db: DB, if_match: IfMatch = None
) -> None:
    """Delete: the file moves to the recovery area and a tombstone revision is kept."""
    file, vault, note = await _load(db, caller, note_id, "editor")
    check_if_match(if_match, file.revision, note.model_dump(mode="json"))
    op = Delete(uuid.uuid7(), file.file_id, file.revision)
    try:
        result = await commit(
            request, vault, op, caller.device_id, None, expected_revision=file.revision
        )
    except StaleRevision:
        result = None
    if result is None or not ok(result):
        if result is not None and result.status == "rejected":
            raise refused(result)
        _, _, current = await _load(db, caller, note_id, "viewer")
        raise _stale(current)
    audit(
        db,
        request,
        "note.delete",
        caller,
        vault_id=vault.id,
        target=str(file.file_id),
        details={"path": file.path},
    )
    await db.commit()


@router.get(
    "/{note_id}/content",
    response_class=Response,
    responses={200: {"content": _MARKDOWN, "headers": _ETAG}},
)
async def get_note_content(
    note_id: uuid.UUID, request: Request, caller: Caller, db: DB
) -> Response:
    """The note's exact bytes."""
    file, vault, note = await _load(db, caller, note_id, "viewer")
    data = await _bytes(request, vault, file.content_hash)
    return Response(
        data, media_type="text/markdown; charset=utf-8", headers={"ETag": etag(note.revision)}
    )


@router.put(
    "/{note_id}/content",
    responses={200: {"headers": _ETAG}},
    openapi_extra={"requestBody": {"required": True, "content": _MARKDOWN}},
)
async def put_note_content(
    note_id: uuid.UUID,
    request: Request,
    caller: Caller,
    db: DB,
    response: Response,
    if_match: IfMatch = None,
) -> Note:
    """Replace the note's bytes (`text/markdown`, at most 16 MiB). A stale `If-Match` is
    a 412 carrying the current note; clients wanting a merge use sync push (Phase 5)."""
    file, vault, note = await _load(db, caller, note_id, "editor")
    check_if_match(if_match, file.revision, note.model_dump(mode="json"))
    data = await _read_body(request)
    op = Update(uuid.uuid7(), file.file_id, file.revision, _sha(data))
    note = await _commit_at(request, db, caller, vault, op, data)
    response.headers["ETag"] = etag(note.revision)
    return note


@router.get("/{note_id}/links")
async def get_note_links(note_id: uuid.UUID, caller: Caller, db: DB) -> NoteLinks:
    """Outgoing links, backlinks and unresolved targets."""
    file, _, _ = await _load(db, caller, note_id, "viewer")
    target, target_note = aliased(File), aliased(NoteRow)
    links = (
        await db.execute(
            select(NoteLink, target.path, target_note.title)
            .outerjoin(target, (target.file_id == NoteLink.resolved_file_id) & ~target.deleted)
            .outerjoin(target_note, target_note.file_id == target.file_id)
            .where(NoteLink.file_id == file.file_id)
            .order_by(NoteLink.ordinal)
        )
    ).all()
    outgoing = [
        OutgoingLink(
            target=link.target,
            resolved=NoteRef(id=link.resolved_file_id, path=path, title=title or _stem(path))
            if path is not None and link.resolved_file_id is not None
            else None,
            embed=link.embed,
            heading=link.heading,
            block=link.block,
            alias=link.alias,
        )
        for link, path, title in links
    ]
    backlinks = (
        await db.execute(
            select(File.file_id, File.path, NoteRow.title)
            .join(NoteLink, NoteLink.file_id == File.file_id)
            .outerjoin(NoteRow, NoteRow.file_id == File.file_id)
            .where(
                NoteLink.resolved_file_id == file.file_id,
                File.file_id != file.file_id,
                ~File.deleted,
            )
            .distinct()
            .order_by(File.path)
        )
    ).all()
    return NoteLinks(
        outgoing=outgoing,
        incoming=[NoteRef(id=i, path=p, title=t or _stem(p)) for i, p, t in backlinks],
        unresolved=list(dict.fromkeys(o.target for o in outgoing if o.resolved is None)),
    )
