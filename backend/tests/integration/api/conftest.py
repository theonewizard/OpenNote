"""Fixtures for the v1 API against real PostgreSQL, Valkey and vault directories:
users, credentials of each kind, and vaults with members."""

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx2 import AsyncClient
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.main import create_app
from app.auth.admin import create_user
from app.auth.crypto import new_secret, secret_hash
from app.auth.dependencies import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from app.auth.models import PersonalAccessToken, User
from app.auth.store import create_device, create_session, issue_device_tokens
from app.core.config import Settings
from app.vaults.models import VaultMember
from app.vaults.registry import open_vault
from tests.integration.conftest import serve

PASSWORD = "correct horse battery"


@dataclass
class Api:
    app: FastAPI
    client: AsyncClient
    engine: Engine
    settings: Settings

    def user(self, username: str = "alice", *, admin: bool = False) -> User:
        with Session(self.engine, expire_on_commit=False) as s, s.begin():
            return create_user(s, username, PASSWORD, admin=admin, display_name=None)

    def vault(self, owner: User | None, name: str = "Work", **members: str) -> uuid.UUID:
        """A vault directory under the vault root, with `owner` as owner and
        `members` as username=role."""
        root = Path(self.settings.vault_root) / f"{name}-{uuid.uuid4().hex[:8]}"
        root.mkdir()
        with Session(self.engine) as s, s.begin():
            vault_id = open_vault(s, root)
            if owner is not None:
                s.add(VaultMember(vault_id=vault_id, user_id=owner.id, role="owner"))
            for username, role in members.items():
                user = s.query(User).filter_by(username=username).one()
                s.add(VaultMember(vault_id=vault_id, user_id=user.id, role=role))
        return vault_id

    async def bearer(self, user: User) -> dict[str, str]:
        async with AsyncSession(self.app.state.engine, expire_on_commit=False) as db:
            device = await create_device(db, user.id, "test device", "linux")
            access, _, _ = await issue_device_tokens(db, device)
            await db.commit()
        return {"Authorization": f"Bearer {access}"}

    async def cookie(self, user: User) -> dict[str, str]:
        """Headers of a web session: the cookies and the CSRF header."""
        async with AsyncSession(self.app.state.engine, expire_on_commit=False) as db:
            secret, csrf, _ = await create_session(db, user)
            await db.commit()
        return {"Cookie": f"{SESSION_COOKIE}={secret}; {CSRF_COOKIE}={csrf}", CSRF_HEADER: csrf}

    def api_key(
        self, user: User, vault_ids: list[uuid.UUID], scope: str = "read"
    ) -> dict[str, str]:
        secret = new_secret("onp_")
        with Session(self.engine) as s, s.begin():
            s.add(
                PersonalAccessToken(
                    user_id=user.id,
                    name="test",
                    token_hash=secret_hash(secret),
                    scope=scope,
                    vault_ids=vault_ids,
                )
            )
        return {"X-API-Key": secret}


@pytest.fixture
async def api(engine: Engine, make_settings: Callable[..., Settings]) -> AsyncIterator[Api]:
    settings = make_settings()
    app = create_app(settings)
    async with serve(app) as client:
        yield Api(app, client, engine, settings)
