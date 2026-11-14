"""The current user, user administration, devices and personal access tokens (P2-02)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError

from app.api.conventions import decode_cursor, encode_cursor, remember, replay, request_hash
from app.api.deps import DB, ROLE_RANK, forbidden, not_found, vault_role
from app.api.http import Cursor, IdempotencyKey, Limit
from app.api.schemas import (
    Device,
    DevicePage,
    PersonalAccessToken,
    PersonalAccessTokenCreate,
    PersonalAccessTokenCreated,
    PersonalAccessTokenPage,
    User,
    UserCreate,
    UserPage,
)
from app.auth.admin import UserExists
from app.auth.admin import create_user as create_user_row
from app.auth.crypto import new_secret, secret_hash
from app.auth.dependencies import Principal, get_current_principal
from app.auth.models import Device as DeviceRow
from app.auth.models import PersonalAccessToken as TokenRow
from app.auth.models import User as UserRow
from app.auth.store import now
from app.core.audit import audit
from app.core.problems import ProblemError

router = APIRouter(prefix="/api/v1", tags=["users"])
Caller = Annotated[Principal, Depends(get_current_principal)]


def _require_admin(principal: Principal) -> None:
    if not principal.is_admin:
        raise forbidden()


def _after(cursor: str | None, length: int) -> list[object] | None:
    """The cursor's values, the last one (the row id) as a UUID."""
    values = decode_cursor(cursor, length)
    if values is None:
        return None
    try:
        return [*values[:-1], uuid.UUID(str(values[-1]))]
    except ValueError:
        raise ProblemError(
            400, "Invalid cursor", "invalid-cursor", "The cursor is not valid."
        ) from None


def _next_cursor[T](rows: list[T], limit: int, key: tuple[str, ...]) -> str | None:
    """The cursor after the page's last row when there is another page (`rows` holds
    one extra row to tell)."""
    if len(rows) <= limit:
        return None
    last = rows[limit - 1]
    return encode_cursor([str(getattr(last, field)) for field in key])


@router.get("/me")
async def get_me(principal: Caller, db: DB) -> User:
    """The signed-in user."""
    user = await db.get(UserRow, principal.user_id)
    if user is None:  # deleted between authentication and here
        raise not_found("User")
    return User.model_validate(user, from_attributes=True)


@router.get("/users")
async def list_users(
    principal: Caller, db: DB, cursor: Cursor = None, limit: Limit = 50
) -> UserPage:
    """Every local and OIDC user (admin only)."""
    _require_admin(principal)
    query = select(UserRow).order_by(UserRow.username_key, UserRow.id).limit(limit + 1)
    if (after := _after(cursor, 2)) is not None:
        query = query.where(tuple_(UserRow.username_key, UserRow.id) > (after[0], after[1]))
    rows = list(await db.scalars(query))
    return UserPage(
        items=[User.model_validate(row, from_attributes=True) for row in rows[:limit]],
        next_cursor=_next_cursor(rows, limit, ("username_key", "id")),
    )


@router.post("/users", status_code=201, response_model=User)
async def create_user(
    body: UserCreate,
    principal: Caller,
    request: Request,
    db: DB,
    idempotency_key: IdempotencyKey = None,
) -> Response:
    """Create a local account (admin only)."""
    _require_admin(principal)
    # The password stays out of the stored fingerprint: a plain SHA-256 of it would be
    # an offline-crackable hash.
    fingerprint = request_hash("POST /api/v1/users", body.model_dump_json(exclude={"password"}))
    if (stored := await replay(db, principal, idempotency_key, fingerprint)) is not None:
        return stored
    try:
        row = await db.run_sync(
            lambda s: create_user_row(
                s,
                body.username,
                body.password,
                admin=body.is_admin,
                display_name=body.display_name,
                email=body.email,
            )
        )
    except UserExists, IntegrityError:  # IntegrityError: a concurrent create won
        await db.rollback()
        raise ProblemError(
            409, "User exists", "user-exists", "A user with this name exists."
        ) from None
    await db.refresh(row)
    audit(db, request, "user.create", principal, target=str(row.id))
    await db.commit()
    response = JSONResponse(
        User.model_validate(row, from_attributes=True).model_dump(mode="json"), status_code=201
    )
    await remember(db, principal, idempotency_key, fingerprint, response)
    return response


@router.get("/devices")
async def list_devices(
    principal: Caller, db: DB, cursor: Cursor = None, limit: Limit = 50
) -> DevicePage:
    """The caller's devices; a device is created by its first token exchange."""
    query = (
        select(DeviceRow)
        .where(DeviceRow.user_id == principal.user_id, DeviceRow.revoked_at.is_(None))
        .order_by(DeviceRow.id)
        .limit(limit + 1)
    )
    if (after := _after(cursor, 1)) is not None:
        query = query.where(DeviceRow.id > after[0])
    rows = list(await db.scalars(query))
    return DevicePage(
        items=[
            Device(
                id=row.id,
                name=row.name,
                platform=row.platform,
                created_at=row.created_at,
                last_seen_at=row.last_seen_at,
                current=str(row.id) == principal.device_id,
            )
            for row in rows[:limit]
        ],
        next_cursor=_next_cursor(rows, limit, ("id",)),
    )


@router.delete("/devices/{device_id}", status_code=204)
async def revoke_device(device_id: uuid.UUID, principal: Caller, request: Request, db: DB) -> None:
    """Revoke a device: its refresh tokens stop working at once, its access token within
    15 minutes."""
    row = await db.get(DeviceRow, device_id)
    if row is None or row.user_id != principal.user_id:
        raise not_found("Device")
    if row.revoked_at is None:
        row.revoked_at = now()
        audit(db, request, "device.revoke", principal, target=str(row.id))
        await db.commit()


def _token_out(row: TokenRow) -> PersonalAccessToken:
    return PersonalAccessToken.model_validate(row, from_attributes=True)


@router.get("/tokens")
async def list_tokens(
    principal: Caller, db: DB, cursor: Cursor = None, limit: Limit = 50
) -> PersonalAccessTokenPage:
    """The caller's personal access tokens (never their secrets)."""
    query = (
        select(TokenRow)
        .where(TokenRow.user_id == principal.user_id, TokenRow.revoked_at.is_(None))
        .order_by(TokenRow.id)
        .limit(limit + 1)
    )
    if (after := _after(cursor, 1)) is not None:
        query = query.where(TokenRow.id > after[0])
    rows = list(await db.scalars(query))
    return PersonalAccessTokenPage(
        items=[_token_out(row) for row in rows[:limit]],
        next_cursor=_next_cursor(rows, limit, ("id",)),
    )


@router.post("/tokens", status_code=201)
async def create_token(
    body: PersonalAccessTokenCreate,
    principal: Caller,
    request: Request,
    db: DB,
    idempotency_key: IdempotencyKey = None,
) -> PersonalAccessTokenCreated:
    """Create a personal access token for automation, limited to the given vaults, in
    which the caller must hold at least the matching role."""
    # Idempotency-Key is accepted but not replayed: a replay would have to store the
    # secret, which is shown once and kept only as a hash.
    needed = ROLE_RANK["editor" if body.scope == "write" else "viewer"]
    vault_ids = list(dict.fromkeys(body.vault_ids))
    for vault_id in vault_ids:
        role = await vault_role(db, principal, vault_id)
        if role is None or ROLE_RANK[role] < needed:
            raise not_found()
    secret = new_secret("onp_")
    row = TokenRow(
        id=uuid.uuid7(),
        user_id=principal.user_id,
        name=body.name,
        token_hash=secret_hash(secret),
        scope=body.scope,
        vault_ids=vault_ids,
        expires_at=body.expires_at,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    audit(db, request, "token.create", principal, target=str(row.id))
    await db.commit()
    return PersonalAccessTokenCreated(token=_token_out(row), secret=secret)


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(token_id: uuid.UUID, principal: Caller, request: Request, db: DB) -> None:
    """Revoke a personal access token."""
    row = await db.get(TokenRow, token_id)
    if row is None or row.user_id != principal.user_id:
        raise not_found("Token")
    if row.revoked_at is None:
        row.revoked_at = now()
        audit(db, request, "token.revoke", principal, target=str(row.id))
        await db.commit()
