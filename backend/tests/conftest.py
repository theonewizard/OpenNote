"""Shared test fixtures. Unit tests contact no service: settings hold placeholders only."""

import os

PLACEHOLDER_ENV = {
    "OPENNOTE_DATABASE_URL": "postgresql+psycopg://opennote:opennote@127.0.0.1:5432/opennote_test",
    "OPENNOTE_VALKEY_URL": "redis://127.0.0.1:6379/0",
    "OPENNOTE_VAULT_ROOT": "/nonexistent/opennote/vaults",
    "OPENNOTE_HISTORY_ROOT": "/nonexistent/opennote/history",
    "OPENNOTE_LOG_LEVEL": "INFO",
    "OPENNOTE_ENVIRONMENT": "test",
}

# app.api.main builds its module-level app on import, reading settings from the
# environment, so the placeholders must be set before the imports below. Any other
# OPENNOTE_* variable (such as *_FILE) is cleared so the shell cannot leak into tests;
# OPENNOTE_TEST_* stay, they point integration tests at their services.
for _name in [n for n in os.environ if n.startswith("OPENNOTE_")]:
    if not _name.startswith("OPENNOTE_TEST_"):
        del os.environ[_name]
os.environ.update(PLACEHOLDER_ENV)

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app.api import main
from app.api.main import create_app
from app.auth.dependencies import Principal, get_current_principal
from app.core.config import Settings


def placeholder_settings() -> Settings:
    """Settings built from the placeholders; nothing is read from disk or contacted."""
    return Settings(**{k.removeprefix("OPENNOTE_").lower(): v for k, v in PLACEHOLDER_ENV.items()})


def as_test_user(app: FastAPI) -> FastAPI:
    """Let requests past get_current_principal, which rejects everyone in Phase 0."""
    app.dependency_overrides[get_current_principal] = lambda: Principal(id="test-user", kind="user")
    return app


@pytest.fixture
def auth() -> dict[str, str]:
    """Credentials for a request; tests that send them also override the auth dependency."""
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def build_app(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FastAPI]:
    """Build the app with extra routers after the real ones, so the auth guard sees them."""

    def build(*routers: APIRouter) -> FastAPI:
        monkeypatch.setattr(main, "ROUTERS", [*main.ROUTERS, *routers])
        return create_app(placeholder_settings())

    return build


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(placeholder_settings())) as test_client:
        yield test_client


@pytest.fixture
def client_with_failing_route(build_app: Callable[..., FastAPI]) -> Iterator[TestClient]:
    router = APIRouter()

    @router.get("/api/v1/boom", dependencies=[Depends(get_current_principal)])
    def boom() -> None:
        raise RuntimeError("boom-secret")

    app = as_test_user(build_app(router))
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def tree_digest(root: Path) -> list[tuple[str, int, int, bytes | None]]:
    """(path, mode, mtime_ns, bytes) of every entry under `root`, directories included."""
    entries = [(".", root.lstat().st_mode, root.lstat().st_mtime_ns, None)]
    for path in sorted(root.rglob("*")):
        st = path.lstat()
        data = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        entries.append((str(path.relative_to(root)), st.st_mode, st.st_mtime_ns, data))
    return entries


@pytest.fixture
def obsidian_vault(tmp_path: Path) -> Path:
    """A copy of the corpus's plain Obsidian vault (no .opennote/config.json)."""
    from tests.compatibility.corpus import CORPUS

    return Path(shutil.copytree(CORPUS / "obsidian-basic" / "vault", tmp_path / "vault"))
