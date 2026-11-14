"""Vault endpoints and vault membership (P2-03). A vault the caller cannot reach is a 404."""

import datetime as dt
import re
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.conventions import (
    check_if_match,
    decode_cursor,
    encode_cursor,
    etag,
    remember,
    replay,
    request_hash,
)
from app.api.deps import DB, ROLE_RANK, forbidden, not_found, require_vault
from app.api.http import Cursor, IdempotencyKey, IfMatch, Limit
from app.api.schemas import (
    Role,
    Vault,
    VaultCreate,
    VaultMember,
    VaultMemberPage,
    VaultMemberPut,
    VaultPage,
    VaultPatch,
    VaultSettings,
)
from app.auth.dependencies import Principal, get_caller, get_current_principal
from app.auth.models import User as UserRow
from app.core.audit import audit
from app.core.problems import ProblemError
from app.vaults.models import Vault as VaultRow
from app.vaults.models import VaultMember as MemberRow
from app.vaults.registry import open_vault

router = APIRouter(prefix="/api/v1/vaults", tags=["vaults"])
Caller = Annotated[Principal, Depends(get_caller)]
User = Annotated[Principal, Depends(get_current_principal)]


def _cap(principal: Principal, role: str) -> Role:
    """The member role, capped by a personal access token's scope (as deps.vault_role)."""
    if principal.pat_scope is not None:
        cap = "editor" if principal.pat_scope == "write" else "viewer"
        role = min(role, cap, key=ROLE_RANK.__getitem__)
    return role  # type: ignore[return-value]


def _vault(row: VaultRow, role: Role) -> Vault:
    return Vault(
        id=row.id,
        name=row.name,
        role=role,
        revision=row.revision,
        created_at=row.created_at,
        settings=VaultSettings.model_validate(row.settings or {}),
    )


def _invalid_directory() -> ProblemError:
    return ProblemError(
        422,
        "Invalid directory",
        "invalid-directory",
        "The directory must be an existing folder inside the vault root.",
    )


def _directory(vault_root: Path, directory: str | None, name: str) -> Path:
    """The vault folder: an existing one under the vault root, reached without `..` or a
    symlink, or a new one named after the vault."""
    base = vault_root.resolve()
    if directory is None:
        slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:60] or "vault"
        root = base / f"{slug}-{uuid.uuid4().hex[:8]}"
        root.mkdir()
        return root
    parts = directory.strip("/").split("/")
    if directory.startswith("/") or any(p in ("", ".", "..") or "\0" in p for p in parts):
        raise _invalid_directory()
    root = base
    for part in parts:
        root = root / part
        if root.is_symlink() or not root.is_dir():
            raise _invalid_directory()
    return root


async def _member_count(db: AsyncSession, vault_id: uuid.UUID, role: str) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(MemberRow)
        .where(MemberRow.vault_id == vault_id, MemberRow.role == role)
    )
    return count or 0


@router.get("")
async def list_vaults(
    caller: Caller, db: DB, cursor: Cursor = None, limit: Limit = 50
) -> VaultPage:
    """The vaults the caller holds a role in."""
    after = decode_cursor(cursor, 1)
    query = (
        select(VaultRow, MemberRow.role)
        .join(MemberRow, MemberRow.vault_id == VaultRow.id)
        .where(MemberRow.user_id == caller.user_id, VaultRow.deleted_at.is_(None))
        .order_by(VaultRow.id)
        .limit(limit + 1)
    )
    if caller.pat_vaults is not None:
        query = query.where(VaultRow.id.in_(caller.pat_vaults))
    if after is not None:
        try:
            query = query.where(VaultRow.id > uuid.UUID(str(after[0])))
        except ValueError:
            raise ProblemError(
                400, "Invalid cursor", "invalid-cursor", "The cursor is not valid."
            ) from None
    rows = (await db.execute(query)).all()
    items = [_vault(row, _cap(caller, role)) for row, role in rows[:limit]]
    more = len(rows) > limit
    return VaultPage(items=items, next_cursor=encode_cursor([str(items[-1].id)]) if more else None)


@router.post("", status_code=201, response_model=Vault)
async def create_vault(
    body: VaultCreate,
    request: Request,
    user: User,
    db: DB,
    idempotency_key: IdempotencyKey = None,
) -> Response:
    """Create an empty vault, or register an existing directory under the vault root
    (admin only). The creator becomes its owner."""
    if not user.is_admin:
        raise forbidden()
    fingerprint = request_hash("POST", "/api/v1/vaults", body.model_dump_json())
    if replayed := await replay(db, user, idempotency_key, fingerprint):
        return replayed
    root = _directory(Path(request.app.state.settings.vault_root), body.directory, body.name)
    if await db.scalar(select(VaultRow.id).where(VaultRow.root_path == str(root))):
        raise ProblemError(
            409, "Vault exists", "vault-exists", "This directory is already a vault."
        )
    # Opening reads the folder's config, if any, and never writes into the folder.
    vault_id = await db.run_sync(lambda session: open_vault(session, root))
    row = await db.get(VaultRow, vault_id)
    if row is None:  # open_vault just recorded it
        raise not_found()
    row.name = body.name
    db.add(MemberRow(vault_id=vault_id, user_id=user.user_id, role="owner"))
    audit(db, request, "vault.create", user, vault_id=vault_id, target=body.name)
    await db.commit()
    await db.refresh(row)
    vault = _vault(row, "owner")
    response = JSONResponse(
        vault.model_dump(mode="json"),
        status_code=201,
        headers={"ETag": etag(row.revision), "Location": f"/api/v1/vaults/{vault_id}"},
    )
    await remember(db, user, idempotency_key, fingerprint, response)
    return response


@router.get("/{vault_id}")
async def get_vault(vault_id: uuid.UUID, caller: Caller, db: DB, response: Response) -> Vault:
    row, role = await require_vault(db, caller, vault_id, "viewer")
    response.headers["ETag"] = etag(row.revision)
    return _vault(row, role)


@router.patch("/{vault_id}")
async def update_vault(
    vault_id: uuid.UUID,
    body: VaultPatch,
    user: User,
    db: DB,
    response: Response,
    if_match: IfMatch = None,
) -> Vault:
    """Rename or change settings (owner)."""
    await require_vault(db, user, vault_id, "owner")
    row = await _locked(db, vault_id)
    check_if_match(if_match, row.revision, _vault(row, "owner").model_dump(mode="json"))
    if body.name is not None:
        row.name = body.name
    if body.settings is not None:
        changes: dict[str, Any] = body.settings.model_dump(exclude_none=True)
        row.settings = (row.settings or {}) | changes
    row.revision += 1
    await db.commit()
    response.headers["ETag"] = etag(row.revision)
    return _vault(row, "owner")


@router.delete("/{vault_id}", status_code=204)
async def delete_vault(
    vault_id: uuid.UUID, request: Request, user: User, db: DB, if_match: IfMatch = None
) -> None:
    """Soft delete (owner): the vault disappears from the API; its files stay on disk."""
    await require_vault(db, user, vault_id, "owner")
    row = await _locked(db, vault_id)
    check_if_match(if_match, row.revision, _vault(row, "owner").model_dump(mode="json"))
    row.deleted_at = dt.datetime.now(dt.UTC)
    row.revision += 1
    audit(db, request, "vault.delete", user, vault_id=vault_id, target=row.name)
    await db.commit()


async def _locked(db: AsyncSession, vault_id: uuid.UUID) -> VaultRow:
    """The vault row, locked and re-read, for a revisioned change."""
    row = await db.scalar(
        select(VaultRow)
        .where(VaultRow.id == vault_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise not_found()
    return row


def _member(member: MemberRow, account: UserRow) -> VaultMember:
    return VaultMember(
        user_id=account.id,
        username=account.username,
        display_name=account.display_name,
        role=member.role,
    )


@router.get("/{vault_id}/members")
async def list_vault_members(
    vault_id: uuid.UUID, user: User, db: DB, cursor: Cursor = None, limit: Limit = 50
) -> VaultMemberPage:
    await require_vault(db, user, vault_id, "owner")
    after = decode_cursor(cursor, 1)
    query = (
        select(MemberRow, UserRow)
        .join(UserRow, UserRow.id == MemberRow.user_id)
        .where(MemberRow.vault_id == vault_id)
        .order_by(UserRow.id)
        .limit(limit + 1)
    )
    if after is not None:
        try:
            query = query.where(UserRow.id > uuid.UUID(str(after[0])))
        except ValueError:
            raise ProblemError(
                400, "Invalid cursor", "invalid-cursor", "The cursor is not valid."
            ) from None
    rows = (await db.execute(query)).all()
    items = [_member(member, account) for member, account in rows[:limit]]
    more = len(rows) > limit
    return VaultMemberPage(
        items=items, next_cursor=encode_cursor([str(items[-1].user_id)]) if more else None
    )


async def _lock_vault(db: AsyncSession, vault_id: uuid.UUID) -> None:
    """Serialize membership changes of one vault, so the last-owner check holds."""
    await db.execute(select(VaultRow.id).where(VaultRow.id == vault_id).with_for_update())


def _last_owner() -> ProblemError:
    return ProblemError(409, "Last owner", "last-owner", "A vault must keep at least one owner.")


@router.put("/{vault_id}/members/{user_id}")
async def put_vault_member(
    vault_id: uuid.UUID,
    user_id: uuid.UUID,
    body: VaultMemberPut,
    request: Request,
    user: User,
    db: DB,
) -> VaultMember:
    """Grant or change a user's role (owner). The last owner cannot be demoted."""
    await require_vault(db, user, vault_id, "owner")
    account = await db.get(UserRow, user_id)
    if account is None or account.disabled:
        raise not_found("User")
    await _lock_vault(db, vault_id)
    member = await db.get(MemberRow, (vault_id, user_id))
    if member is None:
        member = MemberRow(vault_id=vault_id, user_id=user_id, role=body.role)
        db.add(member)
    else:
        if (
            member.role == "owner"
            and body.role != "owner"
            and await _member_count(db, vault_id, "owner") <= 1
        ):
            raise _last_owner()
        member.role = body.role
    audit(
        db,
        request,
        "vault.member_put",
        user,
        vault_id=vault_id,
        target=str(user_id),
        details={"role": body.role},
    )
    await db.commit()
    return _member(member, account)


@router.delete("/{vault_id}/members/{user_id}", status_code=204)
async def remove_vault_member(
    vault_id: uuid.UUID, user_id: uuid.UUID, request: Request, user: User, db: DB
) -> None:
    """Remove a user's access (owner). The last owner cannot be removed."""
    await require_vault(db, user, vault_id, "owner")
    await _lock_vault(db, vault_id)
    member = await db.get(MemberRow, (vault_id, user_id))
    if member is None:
        raise not_found("Member")
    if member.role == "owner" and await _member_count(db, vault_id, "owner") <= 1:
        raise _last_owner()
    await db.delete(member)
    audit(db, request, "vault.member_remove", user, vault_id=vault_id, target=str(user_id))
    await db.commit()
