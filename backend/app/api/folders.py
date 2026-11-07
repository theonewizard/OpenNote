"""Folder endpoints (P2-05). Folders have no revision of their own: a move or a recursive
delete is a batch of file revisions."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.http import IdempotencyKey, VaultIdQuery, not_implemented
from app.api.schemas import Folder, FolderCreate, FolderList, FolderMove, FolderMoveResult
from app.auth.dependencies import Principal, get_caller

router = APIRouter(prefix="/api/v1/folders", tags=["folders"])
Caller = Annotated[Principal, Depends(get_caller)]


@router.get("")
async def list_folders(caller: Caller, vault_id: VaultIdQuery) -> FolderList:
    """Every folder of the vault, empty ones included, sorted by path."""
    raise not_implemented()


@router.post("", status_code=201)
async def create_folder(
    body: FolderCreate, caller: Caller, idempotency_key: IdempotencyKey = None
) -> Folder:
    raise not_implemented()


@router.patch("")
async def move_folder(body: FolderMove, caller: Caller) -> FolderMoveResult:
    """Move or rename a folder: one move revision per file inside it."""
    raise not_implemented()


@router.delete("", status_code=204)
async def delete_folder(
    caller: Caller,
    vault_id: VaultIdQuery,
    path: Annotated[str, Query(min_length=1, max_length=1024)],
    recursive: Annotated[
        bool, Query(description="Also delete the files inside, as tombstone revisions")
    ] = False,
) -> None:
    """Delete an empty folder; with `recursive=true`, its files too. A non-empty folder
    without `recursive` is a 409."""
    raise not_implemented()
