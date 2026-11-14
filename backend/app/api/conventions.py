"""HTTP conventions of the v1 API (API contract §1): ETags and preconditions, opaque
cursors, idempotent POST replay."""

import base64
import binascii
import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import Response
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Principal
from app.auth.models import IdempotencyKey
from app.core.problems import ProblemError

IDEMPOTENCY_HOURS = 24


def etag(revision: int) -> str:
    return f'"{revision}"'


def check_if_match(if_match: str | None, revision: int, current: Mapping[str, Any]) -> None:
    """428 without `If-Match`, 412 with the current resource when it names another revision."""
    if if_match is None:
        raise ProblemError(
            428, "Precondition required", "precondition-required", "Send If-Match with the ETag."
        )
    tags = {tag.strip().removeprefix("W/") for tag in if_match.split(",")}
    if etag(revision) not in tags:
        raise ProblemError(
            412,
            "Precondition failed",
            "precondition-failed",
            "The resource has changed; its current state is in `current`.",
            extensions={"current": dict(current)},
            headers={"ETag": etag(revision)},
        )


def encode_cursor(values: list[Any]) -> str:
    raw = json.dumps(values, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None, length: int) -> list[Any] | None:
    """The values a cursor carries, or None for the first page; 400 when it is not ours."""
    if cursor is None:
        return None
    try:
        values = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except binascii.Error, ValueError, UnicodeDecodeError:
        values = None
    if not isinstance(values, list) or len(values) != length:
        raise ProblemError(400, "Invalid cursor", "invalid-cursor", "The cursor is not valid.")
    return values


def request_hash(*parts: bytes | str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        data = part.encode() if isinstance(part, str) else part
        digest.update(len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def _owner(principal: Principal) -> str:
    return f"{principal.kind}:{principal.pat_id or principal.user_id or principal.id}"


async def replay(
    db: AsyncSession, principal: Principal, key: uuid.UUID | None, fingerprint: str
) -> Response | None:
    """The stored response for this key, or None to go ahead. 422 when the key was used
    for a different request."""
    if key is None:
        return None
    cutoff = func.now() - func.make_interval(0, 0, 0, 0, IDEMPOTENCY_HOURS)
    await db.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < cutoff))
    row = await db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.principal == _owner(principal), IdempotencyKey.key == key
        )
    )
    if row is None:
        return None
    if row.request_hash != fingerprint:
        raise ProblemError(
            422,
            "Idempotency key reused",
            "idempotency-key-reused",
            "This Idempotency-Key was used for a different request.",
        )
    return Response(row.body, status_code=row.status, headers=row.headers)


async def remember(
    db: AsyncSession,
    principal: Principal,
    key: uuid.UUID | None,
    fingerprint: str,
    response: Response,
) -> None:
    """Store a successful response for replay (first writer wins)."""
    if key is None or response.status_code >= 400:
        return
    headers = {
        name: value
        for name, value in response.headers.items()
        if name.lower() in {"content-type", "etag", "location"}
    }
    await db.execute(
        pg_insert(IdempotencyKey)
        .values(
            principal=_owner(principal),
            key=key,
            request_hash=fingerprint,
            status=response.status_code,
            headers=headers,
            body=bytes(response.body),
        )
        .on_conflict_do_nothing()
    )
    await db.commit()
