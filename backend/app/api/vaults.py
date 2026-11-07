"""Vault endpoints and vault membership (P2-03). A vault the caller cannot reach is a 404."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.http import Cursor, IdempotencyKey, IfMatch, Limit, not_implemented
from app.api.schemas import (
    Vault,
    VaultCreate,
    VaultMember,
    VaultMemberPage,
    VaultMemberPut,
    VaultPage,
    VaultPatch,
)
from app.auth.dependencies import Principal, get_caller, get_current_principal

router = APIRouter(prefix="/api/v1/vaults", tags=["vaults"])
Caller = Annotated[Principal, Depends(get_caller)]
User = Annotated[Principal, Depends(get_current_principal)]


@router.get("")
async def list_vaults(caller: Caller, cursor: Cursor = None, limit: Limit = 50) -> VaultPage:
    """The vaults the caller holds a role in."""
    raise not_implemented()


@router.post("", status_code=201)
async def create_vault(
    body: VaultCreate, user: User, idempotency_key: IdempotencyKey = None
) -> Vault:
    """Create an empty vault, or register an existing directory under the vault root
    (admin only). The creator becomes its owner."""
    raise not_implemented()


@router.get("/{vault_id}")
async def get_vault(vault_id: uuid.UUID, caller: Caller) -> Vault:
    raise not_implemented()


@router.patch("/{vault_id}")
async def update_vault(
    vault_id: uuid.UUID, body: VaultPatch, user: User, if_match: IfMatch = None
) -> Vault:
    """Rename or change settings (owner)."""
    raise not_implemented()


@router.delete("/{vault_id}", status_code=204)
async def delete_vault(vault_id: uuid.UUID, user: User, if_match: IfMatch = None) -> None:
    """Soft delete (owner): the vault disappears from the API; its files stay on disk."""
    raise not_implemented()


@router.get("/{vault_id}/members")
async def list_vault_members(
    vault_id: uuid.UUID, user: User, cursor: Cursor = None, limit: Limit = 50
) -> VaultMemberPage:
    raise not_implemented()


@router.put("/{vault_id}/members/{user_id}")
async def put_vault_member(
    vault_id: uuid.UUID, user_id: uuid.UUID, body: VaultMemberPut, user: User
) -> VaultMember:
    """Grant or change a user's role (owner). The last owner cannot be demoted."""
    raise not_implemented()


@router.delete("/{vault_id}/members/{user_id}", status_code=204)
async def remove_vault_member(vault_id: uuid.UUID, user_id: uuid.UUID, user: User) -> None:
    """Remove a user's access (owner). The last owner cannot be removed."""
    raise not_implemented()
