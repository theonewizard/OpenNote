"""Folder endpoints (P2-05). Folders have no revision of their own: a move or a recursive
delete is a batch of file revisions."""

import errno
import os
import posixpath
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import anyio.to_thread
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select

from app.api.conventions import remember, replay, request_hash
from app.api.deps import DB, commit, not_found, require_vault
from app.api.http import IdempotencyKey, VaultIdQuery
from app.api.notes import ok, refused
from app.api.schemas import Folder, FolderCreate, FolderList, FolderMove, FolderMoveResult
from app.auth.dependencies import Principal, get_caller
from app.core.audit import audit
from app.core.problems import ProblemError
from app.notes.models import File
from app.sync.commit import Delete, Move
from app.vaults.fsio import PathEscapeError, open_parent, open_root
from app.vaults.models import Vault
from app.vaults.paths import casefold_key, classify, normalize, validate

router = APIRouter(prefix="/api/v1/folders", tags=["folders"])
Caller = Annotated[Principal, Depends(get_caller)]

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_VISIBLE = ("note", "attachment")  # what the scanner enters; dot-folders are never touched


def _invalid_path() -> ProblemError:
    return ProblemError(
        422, "Invalid path", "invalid-path", "The folder path breaks the vault's path rules."
    )


def _folder_exists() -> ProblemError:
    return ProblemError(409, "Folder exists", "folder-exists", "This folder already exists.")


def _folder_path(path: str) -> str:
    path = normalize(path).strip("/")
    if validate(path, note=False) or classify(path) not in _VISIBLE:
        raise _invalid_path()
    return path


# Disk side (runs in worker threads) ---------------------------------------------------------


def _in_vault[T](vault: Vault, work: Callable[[int], T]) -> T:
    root_fd = open_root(Path(vault.root_path))
    try:
        return work(root_fd)
    except PathEscapeError:
        raise _invalid_path() from None
    finally:
        os.close(root_fd)


def _open_dir(root_fd: int, path: str) -> int | None:
    """A directory fd for `path` (the root for ""), or None when it is not a directory."""
    if not path:
        return os.dup(root_fd)
    try:
        parent, leaf = open_parent(root_fd, path)
    except FileNotFoundError, NotADirectoryError:
        return None
    try:
        return os.open(leaf, _DIR_FLAGS, dir_fd=parent)
    except OSError:
        return None
    finally:
        os.close(parent)


def _subdirs(root_fd: int, path: str) -> list[str]:
    """Every folder under `path` (the whole vault for ""), parents first; no symlinks,
    no dot-folders."""
    found: list[str] = []

    def walk(fd: int, prefix: str) -> None:
        with os.scandir(fd) as it:
            entries = sorted(it, key=lambda e: e.name)
        for entry in entries:
            sub = prefix + normalize(entry.name)
            if classify(sub) not in _VISIBLE or not entry.is_dir(follow_symlinks=False):
                continue
            found.append(sub)
            sub_fd = os.open(entry.name, _DIR_FLAGS, dir_fd=fd)
            try:
                walk(sub_fd, sub + "/")
            finally:
                os.close(sub_fd)

    fd = _open_dir(root_fd, path)
    if fd is not None:
        try:
            walk(fd, path + "/" if path else "")
        finally:
            os.close(fd)
    return found


def _taken_on_disk(root_fd: int, path: str) -> bool:
    """Whether an entry at `path` exists, every segment compared case-insensitively."""
    segments = path.split("/")
    fd = os.dup(root_fd)
    try:
        for depth, segment in enumerate(segments, 1):
            with os.scandir(fd) as it:
                match = next((e for e in it if casefold_key(e.name) == casefold_key(segment)), None)
                if match is None:
                    return False
                if depth == len(segments):
                    return True
                if not match.is_dir(follow_symlinks=False):
                    return False
                sub_fd = os.open(match.name, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = sub_fd
        return False
    finally:
        os.close(fd)


def _mkdir(root_fd: int, path: str, *, exist_ok: bool) -> None:
    parent, leaf = open_parent(root_fd, path, create=True)
    try:
        os.mkdir(leaf, 0o777, dir_fd=parent)
    except FileExistsError:
        if not exist_ok:
            raise
    finally:
        os.close(parent)


def _remove_dirs(root_fd: int, path: str) -> bool:
    """Remove `path` and the folders under it that are empty, deepest first; True when
    `path` is gone. Files (an ignored `.DS_Store`, say) keep their folder."""
    for sub in [*reversed(_subdirs(root_fd, path)), path]:
        try:
            parent, leaf = open_parent(root_fd, sub)
        except FileNotFoundError:
            continue
        try:
            os.rmdir(leaf, dir_fd=parent)
        except OSError as err:
            if err.errno not in (errno.ENOTEMPTY, errno.EEXIST, errno.ENOENT):
                raise
        finally:
            os.close(parent)
    return _open_dir(root_fd, path) is None


# Database side ------------------------------------------------------------------------------


def _under(vault_id: uuid.UUID, path: str) -> Any:
    return (
        File.vault_id == vault_id,
        ~File.deleted,
        File.path_key.startswith(casefold_key(path) + "/", autoescape=True),
    )


async def _exists(db: DB, vault: Vault, path: str) -> bool:
    """A folder or file at `path` on disk, or live files implying the folder."""
    if await anyio.to_thread.run_sync(_in_vault, vault, lambda fd: _taken_on_disk(fd, path)):
        return True
    key = casefold_key(path)
    found = await db.scalar(
        select(File.file_id)
        .where(File.vault_id == vault.id, ~File.deleted)
        .where(or_(File.path_key == key, File.path_key.startswith(key + "/", autoescape=True)))
        .limit(1)
    )
    return found is not None


async def _is_folder(db: DB, vault: Vault, path: str) -> bool:
    """A folder on disk at `path`, or live files implying it."""

    def on_disk(root_fd: int) -> bool:
        fd = _open_dir(root_fd, path)
        if fd is not None:
            os.close(fd)
        return fd is not None

    if await anyio.to_thread.run_sync(_in_vault, vault, on_disk):
        return True
    found = await db.scalar(select(File.file_id).where(*_under(vault.id, path)).limit(1))
    return found is not None


async def _files_under(db: DB, vault: Vault, path: str) -> list[File]:
    query = select(File).where(*_under(vault.id, path)).order_by(File.path)
    return list((await db.scalars(query.execution_options(populate_existing=True))).all())


def _folder(path: str, notes: int = 0, attachments: int = 0) -> Folder:
    parent = posixpath.dirname(path)
    return Folder(
        path=path,
        name=posixpath.basename(path),
        parent=parent or None,
        note_count=notes,
        attachment_count=attachments,
    )


async def _counted(db: DB, vault: Vault, path: str) -> Folder:
    key = casefold_key(path) + "/"
    rest = func.substr(File.path_key, len(key) + 1)
    rows = await db.execute(
        select(File.kind, func.count())
        .where(*_under(vault.id, path), func.strpos(rest, "/") == 0)
        .group_by(File.kind)
    )
    counts = {kind: count for kind, count in rows}
    return _folder(path, counts.get("note", 0), counts.get("attachment", 0))


# Routes -------------------------------------------------------------------------------------


@router.get("")
async def list_folders(caller: Caller, db: DB, vault_id: VaultIdQuery) -> FolderList:
    """Every folder of the vault, empty ones included, sorted by path."""
    vault, _ = await require_vault(db, caller, vault_id, "viewer")
    on_disk = await anyio.to_thread.run_sync(_in_vault, vault, lambda fd: _subdirs(fd, ""))
    counts: dict[str, list[int]] = {path: [0, 0] for path in on_disk}
    files = await db.execute(
        select(File.path, File.kind).where(File.vault_id == vault.id, ~File.deleted)
    )
    for path, kind in files:
        parent = posixpath.dirname(path)
        if parent:
            counts.setdefault(parent, [0, 0])[0 if kind == "note" else 1] += 1
        while parent := posixpath.dirname(parent):  # folders implied by the path
            counts.setdefault(parent, [0, 0])
    return FolderList(items=[_folder(p, *counts[p]) for p in sorted(counts)])


@router.post("", status_code=201, response_model=Folder)
async def create_folder(
    body: FolderCreate,
    request: Request,
    caller: Caller,
    db: DB,
    idempotency_key: IdempotencyKey = None,
) -> Response:
    vault, _ = await require_vault(db, caller, body.vault_id, "editor")
    fingerprint = request_hash("POST", "/api/v1/folders", body.model_dump_json())
    if replayed := await replay(db, caller, idempotency_key, fingerprint):
        return replayed
    path = _folder_path(body.path)
    if await _exists(db, vault, path):
        raise _folder_exists()
    try:
        await anyio.to_thread.run_sync(
            _in_vault, vault, lambda fd: _mkdir(fd, path, exist_ok=False)
        )
    except FileExistsError, NotADirectoryError:
        raise _folder_exists() from None
    response = JSONResponse(_folder(path).model_dump(mode="json"), status_code=201)
    await remember(db, caller, idempotency_key, fingerprint, response)
    return response


@router.patch("")
async def move_folder(
    body: FolderMove, request: Request, caller: Caller, db: DB
) -> FolderMoveResult:
    """Move or rename a folder: one move revision per file inside it."""
    vault, _ = await require_vault(db, caller, body.vault_id, "editor")
    old, new = _folder_path(body.path), _folder_path(body.new_path)
    old_key, new_key = casefold_key(old), casefold_key(new)
    if new_key.startswith(old_key + "/"):
        raise ProblemError(422, "Invalid move", "invalid-move", "A folder cannot move into itself.")
    if not await _is_folder(db, vault, old):
        raise not_found("Folder")
    if new == old:
        return FolderMoveResult(folder=await _counted(db, vault, new), moved_files=0)
    if new_key != old_key and await _exists(db, vault, new):  # a case-only rename may go on
        raise _folder_exists()
    depth = old.count("/") + 1
    moves: list[Move] = []
    for file in await _files_under(db, vault, old):
        target = "/".join([new, *file.path.split("/")[depth:]])
        if validate(target, note=file.kind == "note") or classify(target) not in _VISIBLE:
            raise _invalid_path()  # checked for every file before any moves
        moves.append(Move(uuid.uuid7(), file.file_id, file.revision, target))
    old_dirs = await anyio.to_thread.run_sync(_in_vault, vault, lambda fd: _subdirs(fd, old))

    def make_dirs(root_fd: int) -> None:  # empty subfolders move too
        _mkdir(root_fd, new, exist_ok=True)
        for sub in old_dirs:
            _mkdir(root_fd, "/".join([new, *sub.split("/")[depth:]]), exist_ok=True)

    await anyio.to_thread.run_sync(_in_vault, vault, make_dirs)
    moved = 0
    for move in moves:
        result = await commit(request, vault, move, caller.device_id, None)
        if not ok(result):
            raise refused(result)
        moved += 1
    await anyio.to_thread.run_sync(_in_vault, vault, lambda fd: _remove_dirs(fd, old))
    return FolderMoveResult(folder=await _counted(db, vault, new), moved_files=moved)


@router.delete("", status_code=204)
async def delete_folder(
    request: Request,
    caller: Caller,
    db: DB,
    vault_id: VaultIdQuery,
    path: Annotated[str, Query(min_length=1, max_length=1024)],
    recursive: Annotated[
        bool, Query(description="Also delete the files inside, as tombstone revisions")
    ] = False,
) -> None:
    """Delete an empty folder; with `recursive=true`, its files too. A non-empty folder
    without `recursive` is a 409."""
    vault, _ = await require_vault(db, caller, vault_id, "editor")
    path = _folder_path(path)
    if not await _is_folder(db, vault, path):
        raise not_found("Folder")
    files = await _files_under(db, vault, path)
    subdirs = await anyio.to_thread.run_sync(_in_vault, vault, lambda fd: _subdirs(fd, path))
    not_empty = ProblemError(
        409,
        "Folder not empty",
        "folder-not-empty",
        "The folder is not empty; send recursive=true to delete its contents.",
    )
    if (files or subdirs) and not recursive:
        raise not_empty
    for file in files:
        result = await commit(
            request,
            vault,
            Delete(uuid.uuid7(), file.file_id, file.revision),
            caller.device_id,
            None,
        )
        if not ok(result):
            raise refused(result)
    gone = await anyio.to_thread.run_sync(_in_vault, vault, lambda fd: _remove_dirs(fd, path))
    if not gone and not recursive:
        raise not_empty  # only ignored files (dot files, OS cruft) are in it
    audit(
        db,
        request,
        "folder.delete",
        caller,
        vault_id=vault.id,
        target=path,
        details={"recursive": recursive, "deleted_files": len(files)},
    )
    await db.commit()
