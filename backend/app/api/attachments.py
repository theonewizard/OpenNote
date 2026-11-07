"""Attachment endpoints (P2-06): upload with server-side type sniffing, Range download."""

import codecs
import hashlib
import os
import re
import uuid
from collections.abc import Callable, Coroutine, Iterator
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import anyio.to_thread
import filetype  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import conventions
from app.api.deps import (
    DB,
    ROLE_RANK,
    Role,
    StaleRevision,
    commit,
    forbidden,
    not_found,
    require_vault,
    vault_role,
)
from app.api.http import Cursor, IdempotencyKey, IfMatch, Limit, VaultIdQuery
from app.api.schemas import Attachment, AttachmentPage
from app.auth.dependencies import Principal, _api_key, _authenticate, _bearer, _session, get_caller
from app.core.audit import audit
from app.core.problems import ProblemError
from app.notes.models import File as FileRow
from app.sync.commit import Create, Delete, OpResult
from app.sync.history import HistoryStore
from app.sync.models import Revision
from app.vaults.fsio import PathEscapeError, open_file, open_root
from app.vaults.models import Vault
from app.vaults.paths import casefold_key, classify, normalize, validate

SNIFF_BYTES = 8192  # what filetype reads, and what the text checks look at
_CHUNK = 64 * 1024
_MULTIPART_SLACK = 64 * 1024  # boundaries, part headers and the two form fields
_INLINE = re.compile(r"(image/(?!svg\+xml$)|audio/|video/|application/pdf$)")
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")
_media_types: dict[str, str] = {}  # content hash -> sniffed type, a bounded in-process cache


def too_large(limit: int) -> ProblemError:
    return ProblemError(
        413, "Blob too large", "blob-too-large", f"Attachments are limited to {limit} bytes."
    )


class _UploadRoute(APIRoute):
    """Authenticates an upload before its body is read, and stops reading the body once
    it exceeds the blob limit, so neither an anonymous caller nor an oversized upload
    fills the temporary directory. FastAPI parses a form before running dependencies."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            if request.method != "POST":
                return await handler(request)
            await _authenticate(
                request, await _bearer(request), await _session(request), await _api_key(request)
            )
            max_bytes: int = request.app.state.settings.max_blob_bytes
            limit = max_bytes + _MULTIPART_SLACK
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > limit:
                raise too_large(max_bytes)
            received = 0

            async def receive() -> Any:
                nonlocal received
                message = await request.receive()
                received += len(message.get("body", b""))
                if received > limit:
                    raise too_large(max_bytes)
                return message

            return await handler(Request(request.scope, receive))

        return guarded


router = APIRouter(prefix="/api/v1/attachments", tags=["attachments"], route_class=_UploadRoute)
Caller = Annotated[Principal, Depends(get_caller)]

_ETAG = {"ETag": {"description": 'The revision, `"<revision>"`', "schema": {"type": "string"}}}
_BYTES = {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}


# Sniffing ----------------------------------------------------------------------------------


def sniff(head: bytes, size: int) -> str:
    """The media type of a blob from its first SNIFF_BYTES bytes: magic numbers first, then
    UTF-8 text (HTML, SVG and XML by their opening), else octet-stream."""
    if kind := filetype.guess_mime(head):
        return str(kind)
    try:  # a cut-off head may end inside a character
        text = codecs.getincrementaldecoder("utf-8")().decode(head, final=size <= len(head))
    except UnicodeDecodeError:
        return "application/octet-stream"
    if "\0" in text:
        return "application/octet-stream"
    start = text.lstrip("\ufeff \t\r\n").lower()
    if start.startswith(("<!doctype html", "<html")):
        return "text/html"
    if start.startswith("<svg") or (start.startswith("<?xml") and "<svg" in start):
        return "image/svg+xml"
    if start.startswith("<?xml"):
        return "application/xml"
    return "text/plain"


def _remember_type(content_hash: str, media_type: str) -> str:
    if len(_media_types) >= 10_000:
        _media_types.clear()
    _media_types[content_hash] = media_type
    return media_type


# Reading blobs -----------------------------------------------------------------------------


def _open_vault_file(vault: Vault, row: FileRow) -> int | None:
    """An fd on the vault file when it still has the committed size, else None (the
    watcher has not ingested an outside edit yet; the history store has the bytes)."""
    try:
        root_fd = open_root(Path(vault.root_path))
    except OSError, PathEscapeError:
        return None
    try:
        fd = open_file(root_fd, row.path)
    except OSError, PathEscapeError:
        return None
    finally:
        os.close(root_fd)
    if os.fstat(fd).st_size != row.size:
        os.close(fd)
        return None
    return fd


def _history(request: Request, vault: Vault) -> HistoryStore:
    return HistoryStore(Path(request.app.state.settings.history_root), vault.id)


def _media_type(request: Request, vault: Vault, row: FileRow) -> str:
    """Sniffed from the committed bytes; blocking, so called in a worker thread."""
    if cached := _media_types.get(row.content_hash):
        return cached
    fd = _open_vault_file(vault, row)
    if fd is None:
        head = _history(request, vault).get(row.content_hash)[:SNIFF_BYTES]
    else:
        try:
            head = os.pread(fd, SNIFF_BYTES, 0)
        finally:
            os.close(fd)
    return _remember_type(row.content_hash, sniff(head, row.size))


# Lookups -----------------------------------------------------------------------------------


async def _times(db: AsyncSession, file_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[Any, Any]]:
    rows = await db.execute(
        select(Revision.file_id, func.min(Revision.committed_at), func.max(Revision.committed_at))
        .where(Revision.file_id.in_(file_ids))
        .group_by(Revision.file_id)
    )
    return {file_id: (first, last) for file_id, first, last in rows}


async def _models(
    request: Request, db: AsyncSession, vault: Vault, rows: list[FileRow]
) -> list[Attachment]:
    times = await _times(db, [row.file_id for row in rows])
    types = await anyio.to_thread.run_sync(
        lambda: [_media_type(request, vault, row) for row in rows]
    )
    return [
        Attachment(
            id=row.file_id,
            vault_id=row.vault_id,
            path=row.path,
            revision=row.revision,
            content_hash=row.content_hash,
            size=row.size,
            media_type=media_type,
            created_at=times[row.file_id][0],
            modified_at=times[row.file_id][1],
        )
        for row, media_type in zip(rows, types, strict=True)
    ]


async def _load(
    db: AsyncSession, caller: Principal, attachment_id: uuid.UUID, min_role: Role
) -> tuple[FileRow, Vault]:
    """The live attachment and its vault; 404 alike for missing and unreachable."""
    row = await db.get(FileRow, attachment_id)
    role = await vault_role(db, caller, row.vault_id) if row else None
    vault = await db.get(Vault, row.vault_id) if row and role else None
    if row is None or role is None or vault is None or row.deleted or row.kind != "attachment":
        raise not_found("Attachment")
    if ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise forbidden()
    return row, vault


def _problem(result: OpResult) -> ProblemError:
    problem = result.problem or {}
    slug = str(problem.get("type", "")).rsplit("/", 1)[-1] or "commit-failed"
    return ProblemError(int(problem.get("status", 500)), str(problem.get("title", "")), slug)


def _json(model: Attachment, status: int = 200, **headers: str) -> JSONResponse:
    headers["ETag"] = conventions.etag(model.revision)
    return JSONResponse(model.model_dump(mode="json"), status_code=status, headers=headers)


# Routes ------------------------------------------------------------------------------------


@router.get("")
async def list_attachments(
    request: Request,
    caller: Caller,
    db: DB,
    vault_id: VaultIdQuery,
    folder: Annotated[str | None, Query(max_length=1024)] = None,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> AttachmentPage:
    vault, _ = await require_vault(db, caller, vault_id, "viewer")
    after = conventions.decode_cursor(cursor, 2)
    query = select(FileRow).where(
        FileRow.vault_id == vault_id, FileRow.kind == "attachment", ~FileRow.deleted
    )
    if folder is not None:
        prefix = casefold_key(folder.strip("/"))
        prefix += "/" if prefix else ""
        tail = func.substr(FileRow.path_key, len(prefix) + 1)
        query = query.where(FileRow.path_key.startswith(prefix, autoescape=True))
        query = query.where(func.strpos(tail, "/") == 0)
    if after is not None:
        try:
            last = (str(after[0]), uuid.UUID(str(after[1])))
        except ValueError:
            raise ProblemError(
                400, "Invalid cursor", "invalid-cursor", "The cursor is not valid."
            ) from None
        query = query.where(tuple_(FileRow.path, FileRow.file_id) > last)
    rows = list(await db.scalars(query.order_by(FileRow.path, FileRow.file_id).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        conventions.encode_cursor([rows[-1].path, str(rows[-1].file_id)]) if more else None
    )
    return AttachmentPage(items=await _models(request, db, vault, rows), next_cursor=next_cursor)


@router.post("", status_code=201, responses={201: {"headers": _ETAG}})
async def upload_attachment(
    request: Request,
    caller: Caller,
    db: DB,
    vault_id: Annotated[uuid.UUID, Form()],
    path: Annotated[str, Form(min_length=1, max_length=1024)],
    file: Annotated[UploadFile, File()],
    idempotency_key: IdempotencyKey = None,
) -> Attachment:
    """Upload a new attachment (multipart). The stored `media_type` is sniffed from the
    bytes; the declared type is ignored. An existing path is a 409."""
    vault, _ = await require_vault(db, caller, vault_id, "editor")
    path = normalize(path)
    if violations := validate(path, note=False):
        raise ProblemError(
            422,
            "Invalid path",
            "invalid-path",
            "The path breaks the vault's path rules.",
            extensions={"errors": [{"pointer": "/path", "message": v.code} for v in violations]},
        )
    if classify(path) == "note":
        raise ProblemError(
            422, "Invalid path", "invalid-path", "A .md file is a note: use POST /api/v1/notes."
        )
    if classify(path) != "attachment":
        raise ProblemError(422, "Invalid path", "invalid-path", "This path is not an attachment.")

    max_bytes: int = request.app.state.settings.max_blob_bytes
    digest, size = hashlib.sha256(), 0
    while chunk := await file.read(_CHUNK):
        size += len(chunk)
        if size > max_bytes:
            raise too_large(max_bytes)
        digest.update(chunk)
    content_hash = "sha256:" + digest.hexdigest()

    fingerprint = conventions.request_hash(str(vault_id), path, content_hash)
    if replayed := await conventions.replay(db, caller, idempotency_key, fingerprint):
        return replayed  # type: ignore[return-value]
    taken = await db.scalar(
        select(FileRow.file_id).where(
            FileRow.vault_id == vault_id, FileRow.path_key == casefold_key(path), ~FileRow.deleted
        )
    )
    if taken is not None:
        raise ProblemError(409, "Path is taken", "path-taken", "A file already has this path.")

    await file.seek(0)
    blob = await file.read()  # the Committer takes whole blobs until P5-02 (streaming)
    _remember_type(content_hash, sniff(blob[:SNIFF_BYTES], size))
    op = Create(uuid.uuid7(), uuid.uuid7(), path, "attachment", content_hash)
    result = await commit(request, vault, op, caller.device_id, blob)
    # "conflict": a racing upload took the path first; ours was kept under a copy's name.
    if result.status not in ("applied", "conflict"):
        raise _problem(result)
    row = await db.get(FileRow, result.file_id)
    assert row is not None  # noqa: S101 - the commit above created it
    (model,) = await _models(request, db, vault, [row])
    response = _json(model, 201, Location=f"/api/v1/attachments/{model.id}")
    await conventions.remember(db, caller, idempotency_key, fingerprint, response)
    return response  # type: ignore[return-value]


@router.get("/{attachment_id}", responses={200: {"headers": _ETAG}})
async def get_attachment(
    request: Request, attachment_id: uuid.UUID, caller: Caller, db: DB
) -> Attachment:
    row, vault = await _load(db, caller, attachment_id, "viewer")
    (model,) = await _models(request, db, vault, [row])
    return _json(model)  # type: ignore[return-value]


@router.delete("/{attachment_id}", status_code=204)
async def delete_attachment(
    request: Request, attachment_id: uuid.UUID, caller: Caller, db: DB, if_match: IfMatch = None
) -> None:
    row, vault = await _load(db, caller, attachment_id, "editor")
    (model,) = await _models(request, db, vault, [row])
    current = model.model_dump(mode="json")
    conventions.check_if_match(if_match, row.revision, current)
    op = Delete(uuid.uuid7(), row.file_id, row.revision)
    try:
        result = await commit(
            request, vault, op, caller.device_id, None, expected_revision=row.revision
        )
    except StaleRevision:  # a write landed after our read: answer 412 with it
        result = None
    if result is None or result.status == "merged":
        await db.refresh(row)
        (model,) = await _models(request, db, vault, [row])
        conventions.check_if_match(if_match, row.revision, model.model_dump(mode="json"))
    if result is None or result.status != "applied":
        raise _problem(result) if result else ProblemError(409, "Conflict", "conflict")
    audit(
        db,
        request,
        "attachment.delete",
        caller,
        vault_id=vault.id,
        target=str(row.file_id),
        details={"path": row.path},
    )
    await db.commit()


def _byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """The one range asked for, as (start, end) inclusive; None to send everything (no,
    several or unparsable ranges). 416 when it lies past the end."""
    match = _RANGE.fullmatch((header or "").replace(" ", ""))
    if match is None or match.group(1) == match.group(2) == "":
        return None
    first, last = match.group(1), match.group(2)
    if first:
        start, end = int(first), int(last) if last else size - 1
        if last and end < start:
            return None
    else:
        start, end = max(size - int(last), 0), size - 1
        if int(last) == 0:
            start = size  # an empty suffix is unsatisfiable
    if start >= size:
        raise ProblemError(
            416,
            "Range not satisfiable",
            "range-not-satisfiable",
            "The range lies outside the file.",
            headers={"Content-Range": f"bytes */{size}"},
        )
    return start, min(end, size - 1)


def _stream(fd: int, start: int, length: int) -> Iterator[bytes]:
    try:
        while length > 0:
            chunk = os.pread(fd, min(_CHUNK, length), start)
            if not chunk:
                return
            start, length = start + len(chunk), length - len(chunk)
            yield chunk
    finally:
        os.close(fd)


@router.get(
    "/{attachment_id}/content",
    response_class=Response,
    responses={
        200: {"content": _BYTES, "headers": _ETAG},
        206: {"description": "The requested byte range", "content": _BYTES},
        416: {"description": "Range not satisfiable"},
    },
)
async def get_attachment_content(
    request: Request, attachment_id: uuid.UUID, caller: Caller, db: DB
) -> Response:
    """The bytes, with `Range` support (one range) and `Content-Type` as sniffed; served
    with `X-Content-Type-Options: nosniff` and as a download unless it is an image, PDF,
    audio or video file."""
    row, vault = await _load(db, caller, attachment_id, "viewer")
    media_type = await anyio.to_thread.run_sync(lambda: _media_type(request, vault, row))
    span = _byte_range(request.headers.get("range"), row.size)
    start, end = span or (0, row.size - 1)
    disposition = "inline" if _INLINE.match(media_type) else "attachment"
    name = quote(row.path.rsplit("/", 1)[-1], safe="")
    headers = {
        "ETag": conventions.etag(row.revision),
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{name}",
        "Content-Security-Policy": "sandbox",
        "X-Content-Type-Options": "nosniff",
    }
    if span:
        headers["Content-Range"] = f"bytes {start}-{end}/{row.size}"
    status = 206 if span else 200
    fd = await anyio.to_thread.run_sync(lambda: _open_vault_file(vault, row))
    if fd is not None:
        body = _stream(fd, start, end - start + 1)
        return StreamingResponse(body, status, headers, media_type=media_type)
    data = await anyio.to_thread.run_sync(lambda: _history(request, vault).get(row.content_hash))
    return Response(data[start : end + 1], status, headers, media_type=media_type)
