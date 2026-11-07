"""Request-scoped helpers for the v1 routes: the database session, vault access and the
commit path."""

import os
import threading
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Literal

import anyio.to_thread
from fastapi import Depends, Request
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import Principal
from app.core.config import Settings
from app.core.db import make_sync_engine
from app.core.problems import ProblemError
from app.notes.models import File
from app.sync.commit import Committer, Operation, OpResult
from app.sync.history import HistoryStore
from app.vaults.fsio import open_root
from app.vaults.models import Vault, VaultMember

Role = Literal["viewer", "editor", "owner"]
ROLE_RANK: dict[str, int] = {"viewer": 1, "editor": 2, "owner": 3}


async def db_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(request.app.state.engine, expire_on_commit=False) as session:
        yield session


DB = Annotated[AsyncSession, Depends(db_session)]


def not_found(what: str = "Vault") -> ProblemError:
    """The same answer for a missing resource and one the caller may not see."""
    slug = what.lower() + "-not-found"
    return ProblemError(404, f"{what} not found", slug, f"No such {what.lower()}.")


def forbidden() -> ProblemError:
    return ProblemError(403, "Forbidden", "forbidden", "Your role does not allow this.")


async def vault_role(db: AsyncSession, principal: Principal, vault_id: uuid.UUID) -> Role | None:
    """The caller's role in a live vault, capped by a personal access token's scope
    (`read`: viewer, `write`: editor; a token never administers), or None."""
    if principal.user_id is None:
        return None
    if principal.pat_vaults is not None and vault_id not in principal.pat_vaults:
        return None
    role = await db.scalar(
        select(VaultMember.role)
        .join(Vault, Vault.id == VaultMember.vault_id)
        .where(
            VaultMember.vault_id == vault_id,
            VaultMember.user_id == principal.user_id,
            Vault.deleted_at.is_(None),
        )
    )
    if role is None:
        return None
    if principal.pat_scope is not None:
        cap = "editor" if principal.pat_scope == "write" else "viewer"
        role = min(role, cap, key=ROLE_RANK.__getitem__)
    return role  # type: ignore[return-value]


async def require_vault(
    db: AsyncSession, principal: Principal, vault_id: uuid.UUID, min_role: Role
) -> tuple[Vault, Role]:
    """The vault and the caller's role; 404 without access, 403 when the role is too low."""
    role = await vault_role(db, principal, vault_id)
    vault = await db.get(Vault, vault_id) if role else None
    if vault is None or role is None:
        raise not_found()
    if ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise forbidden()
    return vault, role


class Committers:
    """One Committer per vault for this process, on a synchronous engine (the commit path
    does blocking fsync I/O, so it runs in worker threads)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine: Engine = make_sync_engine(settings)
        self.factory: sessionmaker[Session] = sessionmaker(self.engine)
        self._by_vault: dict[uuid.UUID, Committer] = {}
        self._lock = threading.Lock()

    def get(self, vault_id: uuid.UUID, root_path: str) -> Committer:
        with self._lock:
            committer = self._by_vault.get(vault_id)
            if committer is None:
                history = HistoryStore(Path(self.settings.history_root), vault_id)
                committer = Committer(self.factory, history, open_root(Path(root_path)), vault_id)
                committer.recover()  # finish whatever a crash left before serving writes
                self._by_vault[vault_id] = committer
            return committer

    def close(self) -> None:
        for committer in self._by_vault.values():
            os.close(committer.root_fd)
        self._by_vault.clear()
        self.engine.dispose()


class StaleRevision(Exception):
    """The file is no longer at the revision the request was based on."""


async def commit(
    request: Request,
    vault: Vault,
    op: Operation,
    device_id: str,
    blob: bytes | None,
    *,
    expected_revision: int | None = None,
) -> OpResult:
    """Commit `op`. With `expected_revision`, only while the file is still at that
    revision (else StaleRevision): checked under the vault lock, so two requests based on
    the same revision cannot both commit (a REST write never merges)."""
    committers: Committers = request.app.state.committers

    def run() -> OpResult:
        committer = committers.get(vault.id, vault.root_path)
        with committer._vault_lock():  # re-entered by commit(): check and commit are atomic
            if expected_revision is not None:
                with committer.session_factory() as session:
                    row = session.get(File, op.file_id)
                if row is None or row.revision != expected_revision:
                    raise StaleRevision
            return committer.commit(op, device_id, blob)

    return await anyio.to_thread.run_sync(run)
