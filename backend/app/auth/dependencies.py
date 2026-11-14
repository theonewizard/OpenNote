"""Authentication dependencies; every non-keyless route needs one (CLAUDE.md §12).

Three credentials (ADR-0012, Phase 2 plan R-P2-002, R-P2-004):
- `Authorization: Bearer <access token>`: EdDSA JWT of a user's device, 15 minutes;
- the web session cookie, plus `X-CSRF-Token` on mutating requests;
- `X-API-Key: <personal access token>`, limited to the token's vaults and scope.

`get_current_principal` takes the first two (people), `get_api_key` the third,
`get_caller` any of them. Each rejects a missing or invalid credential with a 401 problem.
"""

import datetime as dt
import hmac
import uuid
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Request
from fastapi.security import APIKeyCookie, APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import csrf_token, secret_hash, token_kid, verify_access_token
from app.auth.models import Device, PersonalAccessToken, SigningKey, User, WebSession
from app.core.problems import ProblemError

SESSION_COOKIE = "opennote_session"
CSRF_COOKIE = "opennote_csrf"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_bearer = HTTPBearer(auto_error=False)
_api_key = APIKeyHeader(name="X-API-Key", auto_error=False)
_session = APIKeyCookie(
    name=SESSION_COOKIE,
    auto_error=False,
    description="Web session (httpOnly). Mutating requests also need `X-CSRF-Token`.",
)


@dataclass(frozen=True)
class Principal:
    """Who is calling. `device_id` is what the commit path records as the device."""

    id: str
    kind: Literal["user", "device", "api_key"]
    user_id: uuid.UUID | None = None
    device_id: str = "unknown"
    is_admin: bool = False
    pat_id: uuid.UUID | None = None
    pat_vaults: frozenset[uuid.UUID] | None = None  # None: not limited by a token
    pat_scope: Literal["read", "write"] | None = None
    session_id: uuid.UUID | None = None


def _unauthenticated() -> ProblemError:
    return ProblemError(
        401, "Authentication required", "unauthenticated", "Valid credentials are required."
    )


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def _active_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or user.disabled:
        raise _unauthenticated()
    return user


async def _from_bearer(db: AsyncSession, token: str) -> Principal:
    kid = token_kid(token)
    key = await db.get(SigningKey, kid) if kid else None
    claims = verify_access_token(token, key.private_pem) if key else None
    if claims is None:
        raise _unauthenticated()
    try:
        user_id, device_id = uuid.UUID(claims["sub"]), uuid.UUID(claims["dev"])
    except ValueError:
        raise _unauthenticated() from None
    device = await db.get(Device, device_id)
    if device is None or device.revoked_at is not None or device.user_id != user_id:
        raise _unauthenticated()
    user = await _active_user(db, user_id)
    return Principal(
        id=str(user.id),
        kind="device",
        user_id=user.id,
        device_id=str(device.id),
        is_admin=user.is_admin,
    )


async def _from_session(db: AsyncSession, request: Request, secret: str) -> Principal:
    row = await db.scalar(select(WebSession).where(WebSession.token_hash == secret_hash(secret)))
    if row is None or row.revoked_at is not None or row.expires_at <= _now():
        raise _unauthenticated()
    if request.method not in _SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(sent.encode(), csrf_token(secret).encode()):
            raise ProblemError(
                403, "CSRF check failed", "csrf-failed", "Missing or wrong CSRF token."
            )
    user = await _active_user(db, row.user_id)
    return Principal(
        id=str(user.id),
        kind="user",
        user_id=user.id,
        device_id="web",
        is_admin=user.is_admin,
        session_id=row.id,
    )


async def _from_api_key(db: AsyncSession, secret: str) -> Principal:
    row = await db.scalar(
        select(PersonalAccessToken).where(PersonalAccessToken.token_hash == secret_hash(secret))
    )
    now = _now()
    if row is None or row.revoked_at is not None or (row.expires_at and row.expires_at <= now):
        raise _unauthenticated()
    user = await _active_user(db, row.user_id)
    await db.execute(
        update(PersonalAccessToken).where(PersonalAccessToken.id == row.id).values(last_used_at=now)
    )
    await db.commit()
    scope: Literal["read", "write"] = "write" if row.scope == "write" else "read"
    return Principal(
        id=str(user.id),
        kind="api_key",
        user_id=user.id,
        device_id=f"pat:{row.id}",
        pat_id=row.id,
        pat_vaults=frozenset(row.vault_ids),
        pat_scope=scope,
    )


async def _authenticate(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None,
    session: str | None,
    api_key: str | None,
) -> Principal:
    if bearer is None and not api_key and not session:
        raise _unauthenticated()  # before any database work
    async with AsyncSession(request.app.state.engine, expire_on_commit=False) as db:
        if bearer is not None:
            return await _from_bearer(db, bearer.credentials)
        if api_key:
            return await _from_api_key(db, api_key)
        if session:
            return await _from_session(db, request, session)
    raise _unauthenticated()


async def get_current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[str | None, Depends(_session)],
) -> Principal:
    """The user or device behind an OAuth 2.0 access token (`Authorization: Bearer`) or
    the web session cookie."""
    return await _authenticate(request, credentials, session, None)


async def get_api_key(
    request: Request, api_key: Annotated[str | None, Depends(_api_key)]
) -> Principal:
    """The automation token owner behind the `X-API-Key` header."""
    if not api_key:
        raise _unauthenticated()
    return await _authenticate(request, None, None, api_key)


async def get_caller(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[str | None, Depends(_session)],
    api_key: Annotated[str | None, Depends(_api_key)],
) -> Principal:
    """Whoever is calling, by any of the three credentials; for the vault-scoped routes a
    personal access token may also reach (the token's vaults and scope still apply)."""
    return await _authenticate(request, credentials, session, api_key)
