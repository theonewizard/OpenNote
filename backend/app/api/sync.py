"""Sync endpoints (P5-01, docs/architecture/sync-protocol.md): content-addressed blobs,
pull by cursor, snapshot for a full reconcile, push, conflicts and change hints.

Everything goes through the same Committer as the REST note endpoints, so a push and a
`PUT /notes/{id}/content` follow one commit procedure (API contract §4).
"""

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Literal

import anyio.to_thread
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select

from app.api.conventions import (
    check_if_match,
    decode_cursor,
    encode_cursor,
    etag,
    remember,
    replay,
    request_hash,
)
from app.api.deps import DB, Committers, Role, not_found, require_vault
from app.api.http import IdempotencyKey, IfMatch, Limit, VaultIdQuery
from app.api.schemas import (
    Conflict,
    ConflictPage,
    ConflictPatch,
    PushCreate,
    PushDelete,
    PushMove,
    PushOperation,
    PushResult,
    PushUpdate,
    SyncChanges,
    SyncEntry,
    SyncPush,
    SyncPushResult,
    SyncSnapshot,
)
from app.auth.dependencies import Principal, get_caller
from app.auth.models import Device
from app.core.problems import ProblemError
from app.sync import service
from app.sync.commit import Create, Delete, Move, Operation, OpResult, Restore, Update
from app.sync.cursor import CursorExpired
from app.sync.cursor import encode_cursor as encode_sync_cursor
from app.sync.events import channel
from app.sync.history import HistoryStore
from app.sync.models import Conflict as ConflictRow
from app.vaults.models import Vault, VaultMember
from app.vaults.paths import normalize

router = APIRouter(prefix="/api/v1")
Caller = Annotated[Principal, Depends(get_caller)]
Sha256 = Annotated[
    str, Path(pattern=r"^[0-9a-f]{64}$", description="Lowercase hex SHA-256 of the bytes")
]
_BYTES = {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}
_ETAG = {"ETag": {"description": 'The revision, `"<revision>"`', "schema": {"type": "string"}}}
_CHUNK = 1 << 20

HEARTBEAT_SECONDS = 25.0  # below the 60 s idle timeout of nginx and most proxies
STREAM_SECONDS = 15 * 60  # an access token's lifetime: the client reconnects with a fresh one


def _committers(request: Request) -> Committers:
    committers: Committers = request.app.state.committers
    return committers


def _history(request: Request, vault_id: uuid.UUID) -> HistoryStore:
    return HistoryStore(request.app.state.settings.history_root, vault_id)


# Blobs ------------------------------------------------------------------------------------


def _blob_not_found() -> ProblemError:
    return ProblemError(404, "Blob not found", "blob-not-found", "No blob with this hash.")


def _blob_too_large(limit: int) -> ProblemError:
    return ProblemError(
        413, "Blob too large", "blob-too-large", f"Blobs are limited to {limit} bytes."
    )


@router.head("/blobs/{sha256}", tags=["sync"], status_code=200, response_class=Response)
async def head_blob(
    sha256: Sha256, request: Request, caller: Caller, db: DB, vault_id: VaultIdQuery
) -> Response:
    """200 when the vault's store holds the blob, else 404: upload only what is missing."""
    await require_vault(db, caller, vault_id, "viewer")
    if not _history(request, vault_id).has("sha256:" + sha256):
        raise _blob_not_found()
    return Response(status_code=200)


@router.get(
    "/blobs/{sha256}",
    tags=["sync"],
    response_class=StreamingResponse,
    responses={200: {"content": _BYTES}},
)
async def get_blob(
    sha256: Sha256, request: Request, caller: Caller, db: DB, vault_id: VaultIdQuery
) -> StreamingResponse:
    """The blob's bytes, for a pulled change. Check them against the hash."""
    await require_vault(db, caller, vault_id, "viewer")
    try:
        chunks = _history(request, vault_id).stream("sha256:" + sha256)
    except FileNotFoundError:
        raise _blob_not_found() from None
    # A synchronous iterator: Starlette reads it in a worker thread.
    return StreamingResponse(chunks, media_type="application/octet-stream")


@router.put(
    "/blobs/{sha256}",
    tags=["sync"],
    status_code=204,
    response_class=Response,
    openapi_extra={"requestBody": {"required": True, "content": _BYTES}},
)
async def put_blob(
    sha256: Sha256, request: Request, caller: Caller, db: DB, vault_id: VaultIdQuery
) -> Response:
    """Upload a blob before pushing the operation that names it. The bytes must hash to
    `sha256` (else 422); uploading a blob the store already holds is a no-op."""
    await require_vault(db, caller, vault_id, "editor")
    limit: int = request.app.state.settings.max_blob_bytes
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise _blob_too_large(limit)
    history = _history(request, vault_id)
    content_hash = "sha256:" + sha256
    if history.has(content_hash):
        return Response(status_code=204)
    writer = await anyio.to_thread.run_sync(history.writer)
    try:
        async for chunk in request.stream():
            if writer.size + len(chunk) > limit:
                raise _blob_too_large(limit)
            await anyio.to_thread.run_sync(writer.write, chunk)
        stored = await anyio.to_thread.run_sync(writer.finish, content_hash)
    except BaseException:
        await anyio.to_thread.run_sync(writer.abort)
        raise
    if not stored:
        raise ProblemError(
            422, "Hash mismatch", "blob-hash-mismatch", "The bytes do not match the hash."
        )
    return Response(status_code=204)


# Pull -------------------------------------------------------------------------------------


def _entries(entries: list[service.ChangeEntry]) -> list[SyncEntry]:
    return [SyncEntry.model_validate(e, from_attributes=True) for e in entries]


@router.get("/sync/{vault_id}/changes", tags=["sync"])
async def get_changes(
    vault_id: uuid.UUID,
    request: Request,
    caller: Caller,
    db: DB,
    cursor: Annotated[
        str | None,
        Query(
            max_length=256, description="`next_cursor` of the last pull; omitted, from the start"
        ),
    ] = None,
    limit: Limit = 500,
) -> SyncChanges:
    """Committed revisions after `cursor`, in commit order. A cursor older than the
    tombstone retention window is a 410: run a full reconcile from the snapshot."""
    await require_vault(db, caller, vault_id, "viewer")
    factory = _committers(request).factory

    def run() -> service.ChangesPage:
        with factory() as session:
            return service.changes(session, vault_id, cursor, limit)

    try:
        page = await anyio.to_thread.run_sync(run)
    except CursorExpired:
        raise ProblemError(
            410,
            "Cursor expired",
            "cursor-expired",
            "The cursor is older than the retention window; reconcile from the snapshot.",
        ) from None
    except ValueError:
        raise ProblemError(
            400, "Invalid cursor", "invalid-cursor", "The cursor is not valid."
        ) from None
    return SyncChanges(
        entries=_entries(page.entries), next_cursor=page.next_cursor, has_more=page.has_more
    )


@router.get("/sync/{vault_id}/snapshot", tags=["sync"])
async def get_snapshot(
    vault_id: uuid.UUID,
    request: Request,
    caller: Caller,
    db: DB,
    page: Annotated[
        str | None, Query(max_length=4096, description="`next_page` of the previous page")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=5000, description="Page size")] = 1000,
) -> SyncSnapshot:
    """Every live file at its current revision, for a full reconcile (sync protocol §4).
    Read every page, then pull changes from `cursor`: a change committed while paging is
    in that pull, so the client converges even though the pages are not one instant."""
    await require_vault(db, caller, vault_id, "viewer")
    token = decode_cursor(page, 2)
    if token is not None and not (isinstance(token[0], int) and isinstance(token[1], str)):
        raise ProblemError(400, "Invalid cursor", "invalid-cursor", "The cursor is not valid.")
    factory = _committers(request).factory

    def run() -> tuple[int, list[service.ChangeEntry]]:
        with factory() as session:
            # The seq first: a commit after it is pulled later even if a page shows it.
            seq = token[0] if token else service.last_seq(session, vault_id)
            after = token[1] if token else None
            return seq, service.snapshot(session, vault_id, after, limit + 1)

    seq, rows = await anyio.to_thread.run_sync(run)
    next_page = encode_cursor([seq, rows[limit - 1].path]) if len(rows) > limit else None
    return SyncSnapshot(
        entries=_entries(rows[:limit]),
        cursor=encode_sync_cursor(vault_id, seq),
        next_page=next_page,
    )


# Push -------------------------------------------------------------------------------------


def _operation(op: PushOperation) -> Operation:
    match op:
        case PushCreate():
            return Create(op.client_op_id, op.file_id, normalize(op.path), op.kind, op.content_hash)
        case PushUpdate():
            return Update(op.client_op_id, op.file_id, op.base_revision, op.content_hash)
        case PushMove():
            return Move(op.client_op_id, op.file_id, op.base_revision, normalize(op.new_path))
        case PushDelete():
            return Delete(op.client_op_id, op.file_id, op.base_revision)
    return Restore(op.client_op_id, op.file_id, op.from_revision)


async def _device_name(db: DB, caller: Principal) -> str:
    """What conflict copies are named after: the device's name, else the kind of caller."""
    if caller.kind == "device":
        name = await db.scalar(select(Device.name).where(Device.id == uuid.UUID(caller.device_id)))
        if name:
            return str(name)
    return "web" if caller.kind == "user" else "api"


@router.post("/sync/{vault_id}/push", tags=["sync"])
async def push(
    vault_id: uuid.UUID,
    body: SyncPush,
    request: Request,
    caller: Caller,
    db: DB,
    idempotency_key: IdempotencyKey = None,
) -> SyncPushResult:
    """Commit up to 100 operations in order, each on its own (sync protocol §5). Upload
    each operation's blob first; a missing blob makes that operation `rejected`.
    Retrying an operation with the same `client_op_id` returns its first result as
    `duplicate`; the `Idempotency-Key` replays a whole batch."""
    vault, _ = await require_vault(db, caller, vault_id, "editor")
    fingerprint = request_hash("POST", f"/api/v1/sync/{vault_id}/push", body.model_dump_json())
    if replayed := await replay(db, caller, idempotency_key, fingerprint):
        return replayed  # type: ignore[return-value]
    name = await _device_name(db, caller)
    ops = [_operation(op) for op in body.operations]
    committers = _committers(request)

    def run() -> list[OpResult]:
        committer = committers.get(vault.id, vault.root_path)
        results = []
        for op in ops:
            content_hash = getattr(op, "content_hash", None)
            blob = None
            if content_hash and committer.history.has(content_hash):
                blob = committer.history.get(content_hash)
            results.append(committer.commit(op, caller.device_id, blob, name))
        return results

    results = await anyio.to_thread.run_sync(run)
    body_out = SyncPushResult(
        results=[PushResult.model_validate(r, from_attributes=True) for r in results]
    )
    response = JSONResponse(body_out.model_dump(mode="json"))
    await remember(db, caller, idempotency_key, fingerprint, response)
    return response  # type: ignore[return-value]


# Conflicts --------------------------------------------------------------------------------


def _conflict(row: ConflictRow) -> Conflict:
    return Conflict.model_validate(row, from_attributes=True)


@router.get("/conflicts", tags=["sync"])
async def list_conflicts(
    caller: Caller,
    db: DB,
    vault_id: VaultIdQuery,
    status: Annotated[
        Literal["open", "resolved"] | None, Query(description="Only this status; open by default")
    ] = "open",
    cursor: Annotated[str | None, Query(max_length=256)] = None,
    limit: Limit = 50,
) -> ConflictPage:
    """The vault's conflicts, oldest first; open ones by default."""
    await require_vault(db, caller, vault_id, "viewer")
    query = select(ConflictRow).where(ConflictRow.vault_id == vault_id)
    if status is not None:
        query = query.where(ConflictRow.status == status)
    if (after := decode_cursor(cursor, 1)) is not None:
        try:
            query = query.where(ConflictRow.id > uuid.UUID(str(after[0])))
        except ValueError:
            raise ProblemError(
                400, "Invalid cursor", "invalid-cursor", "The cursor is not valid."
            ) from None
    rows = (await db.scalars(query.order_by(ConflictRow.id).limit(limit + 1))).all()
    next_cursor = encode_cursor([str(rows[limit - 1].id)]) if len(rows) > limit else None
    return ConflictPage(items=[_conflict(r) for r in rows[:limit]], next_cursor=next_cursor)


async def _load_conflict(
    db: DB, caller: Principal, conflict_id: uuid.UUID, role: Role
) -> ConflictRow:
    row = await db.get(ConflictRow, conflict_id)
    if row is None:
        raise not_found("Conflict")
    try:
        await require_vault(db, caller, row.vault_id, role)
    except ProblemError as err:
        if err.status_code == 404:
            raise not_found("Conflict") from None
        raise
    return row


@router.get("/conflicts/{conflict_id}", tags=["sync"], responses={200: {"headers": _ETAG}})
async def get_conflict(
    conflict_id: uuid.UUID, caller: Caller, db: DB, response: Response
) -> Conflict:
    row = await _load_conflict(db, caller, conflict_id, "viewer")
    response.headers["ETag"] = etag(row.revision)
    return _conflict(row)


@router.patch("/conflicts/{conflict_id}", tags=["sync"], responses={200: {"headers": _ETAG}})
async def update_conflict(
    conflict_id: uuid.UUID,
    body: ConflictPatch,
    caller: Caller,
    db: DB,
    response: Response,
    if_match: IfMatch = None,
) -> Conflict:
    """Mark a conflict resolved (or open again). Resolving changes no file: the user
    edits or deletes the copy; both versions stay in history."""
    row = await _load_conflict(db, caller, conflict_id, "editor")
    check_if_match(if_match, row.revision, _conflict(row).model_dump(mode="json"))
    if row.status != body.status:
        row.status = body.status
        row.resolved_at = None if body.status == "open" else func.now()
        row.revision += 1
        await db.commit()
        await db.refresh(row)
    response.headers["ETag"] = etag(row.revision)
    return _conflict(row)


# Change hints -----------------------------------------------------------------------------


async def _vault_ids(db: DB, caller: Principal) -> list[uuid.UUID]:
    """The live vaults the caller may read (every role reads; a token only its vaults)."""
    ids = (
        await db.scalars(
            select(VaultMember.vault_id)
            .join(Vault, Vault.id == VaultMember.vault_id)
            .where(VaultMember.user_id == caller.user_id, Vault.deleted_at.is_(None))
            .order_by(VaultMember.vault_id)
        )
    ).all()
    return [v for v in ids if caller.pat_vaults is None or v in caller.pat_vaults]


_SSE_EVENT = {
    "type": "object",
    "description": "One event: `ready` `{vaults: [uuid]}` once, then `change` "
    "`{vault_id, seq}`; `data` is JSON",
    "required": ["event", "data"],
    "properties": {
        "event": {"type": "string", "enum": ["ready", "change"]},
        "data": {"type": "string", "contentMediaType": "application/json"},
    },
}


def _event(name: str, data: object) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


@router.get(
    "/events",
    tags=["sync"],
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {"schema": _SSE_EVENT}}}},
)
async def events(request: Request, caller: Caller, db: DB) -> StreamingResponse:
    """Change hints as Server-Sent Events: `ready` with the subscribed vaults, then a
    `change` `{vault_id, seq}` after each commit in one of them. Hints are advisory: pull
    on `ready` and on every hint; correctness never depends on them. The stream ends
    after 15 minutes (reconnect with a current token); vaults joined meanwhile are
    included on reconnect."""
    vault_ids = await _vault_ids(db, caller)
    await db.close()  # the stream is long; hold no pooled connection
    url = str(request.app.state.settings.valkey_url)
    return StreamingResponse(
        _hints(url, vault_ids, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def _hints(url: str, vault_ids: list[uuid.UUID], request: Request) -> AsyncIterator[bytes]:
    yield b"retry: 5000\n\n"
    client = Redis.from_url(url, socket_connect_timeout=2)
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    try:
        if vault_ids:
            await pubsub.subscribe(*(channel(v) for v in vault_ids))
        yield _event("ready", {"vaults": [str(v) for v in vault_ids]})
        end = time.monotonic() + STREAM_SECONDS
        beat = time.monotonic() + HEARTBEAT_SECONDS
        while (now := time.monotonic()) < end and not await request.is_disconnected():
            message = None
            if vault_ids:
                message = await pubsub.get_message(timeout=min(1.0, beat - now))
            else:
                await asyncio.sleep(min(1.0, max(beat - now, 0)))
            if message and message.get("type") == "message":
                vault = message["channel"].decode().rsplit(":", 1)[1]
                yield _event("change", {"vault_id": vault, "seq": int(message["data"])})
            if time.monotonic() >= beat:
                yield b": keep-alive\n\n"
                beat = time.monotonic() + HEARTBEAT_SECONDS
    except RedisError:
        pass  # the client reconnects (retry) and pulls; nothing is lost
    finally:
        await pubsub.aclose()  # type: ignore[no-untyped-call]
        await client.aclose()
