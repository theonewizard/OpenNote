"""The current user, user administration, devices and personal access tokens (P2-02)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DB, not_found
from app.api.http import Cursor, IdempotencyKey, Limit, not_implemented
from app.api.schemas import (
    DevicePage,
    PersonalAccessTokenCreate,
    PersonalAccessTokenCreated,
    PersonalAccessTokenPage,
    User,
    UserCreate,
    UserPage,
)
from app.auth.dependencies import Principal, get_current_principal
from app.auth.models import User as UserRow

router = APIRouter(prefix="/api/v1", tags=["users"])
Caller = Annotated[Principal, Depends(get_current_principal)]


@router.get("/me")
async def get_me(principal: Caller, db: DB) -> User:
    """The signed-in user."""
    user = await db.get(UserRow, principal.user_id)
    if user is None:  # deleted between authentication and here
        raise not_found("User")
    return User.model_validate(user, from_attributes=True)


@router.get("/users")
async def list_users(principal: Caller, cursor: Cursor = None, limit: Limit = 50) -> UserPage:
    """Every local and OIDC user (admin only)."""
    raise not_implemented()


@router.post("/users", status_code=201)
async def create_user(
    body: UserCreate, principal: Caller, idempotency_key: IdempotencyKey = None
) -> User:
    """Create a local account (admin only)."""
    raise not_implemented()


@router.get("/devices")
async def list_devices(principal: Caller, cursor: Cursor = None, limit: Limit = 50) -> DevicePage:
    """The caller's devices; a device is created by its first token exchange."""
    raise not_implemented()


@router.delete("/devices/{device_id}", status_code=204)
async def revoke_device(device_id: uuid.UUID, principal: Caller) -> None:
    """Revoke a device: its refresh tokens stop working at once, its access token within
    15 minutes."""
    raise not_implemented()


@router.get("/tokens")
async def list_tokens(
    principal: Caller, cursor: Cursor = None, limit: Limit = 50
) -> PersonalAccessTokenPage:
    """The caller's personal access tokens (never their secrets)."""
    raise not_implemented()


@router.post("/tokens", status_code=201)
async def create_token(
    body: PersonalAccessTokenCreate, principal: Caller, idempotency_key: IdempotencyKey = None
) -> PersonalAccessTokenCreated:
    """Create a personal access token for automation, limited to the given vaults, in
    which the caller must hold at least the matching role."""
    raise not_implemented()


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(token_id: uuid.UUID, principal: Caller) -> None:
    """Revoke a personal access token."""
    raise not_implemented()
