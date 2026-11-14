"""Contract tests (P2-10): Schemathesis generates requests for every operation of the
OpenAPI document the code produces (the one committed as docs/api/openapi.json) and checks
the responses against it. The app runs under uvicorn on a local port, against the test
PostgreSQL, with a signed-in user who owns a vault holding one note."""

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
import schemathesis
import uvicorn
from hypothesis import HealthCheck, settings
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from app.api.main import create_app
from app.auth.admin import create_user
from app.auth.store import create_device, issue_device_tokens
from app.vaults.models import VaultMember
from app.vaults.registry import open_vault


def _bearer_token(engine, user) -> str:
    async def issue() -> str:
        async_engine = create_async_engine(engine.url)
        try:
            async with AsyncSession(async_engine) as db:
                device = await create_device(db, user.id, "contract", None)
                access, _, _ = await issue_device_tokens(db, device)
                await db.commit()
                return access
        finally:
            await async_engine.dispose()

    return asyncio.run(issue())


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def served(engine, make_settings) -> Iterator[dict[str, Any]]:
    settings_ = make_settings()
    app = create_app(settings_)
    root = settings_.vault_root / "Work"
    root.mkdir()
    (root / "a.md").write_bytes(b"---\ntags: [x]\n---\n# A\n")
    with Session(engine, expire_on_commit=False) as s, s.begin():
        user = create_user(s, "contract", "a long enough password", admin=True, display_name=None)
        vault_id = open_vault(s, root)
        s.add(VaultMember(vault_id=vault_id, user_id=user.id, role="owner"))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    # A bearer token, not the web session: logout would end a session for every later case.
    login = httpx2.post(
        f"{base}/api/v1/auth/login",
        json={"username": "contract", "password": "a long enough password"},
    )
    assert login.status_code == 200, login.text  # password login works end to end
    bearer = _bearer_token(engine, user)
    yield {
        "app": app,
        "base_url": base,
        "headers": {"Authorization": f"Bearer {bearer}"},
        "vault_id": str(vault_id),
    }
    server.should_exit = True
    thread.join(10)


@pytest.fixture
def api_schema(served):
    return schemathesis.openapi.from_dict(served["app"].openapi())


# The change-hint stream stays open for 15 minutes, longer than a case may take;
# test_sync.py reads it over a real server instead.
schema = schemathesis.pytest.from_fixture("api_schema").exclude(path="/api/v1/events")

# Checks the API's rules make inapplicable, each with its reason:
EXCLUDED_CHECKS = [
    # Schema-valid is not the same as acceptable: an unknown OAuth client, a vault id the
    # caller cannot see (404 by design), a path that breaks the path rules, a stale If-Match.
    schemathesis.checks.positive_data_acceptance,
]


@schema.parametrize()
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    derandomize=True,
)
def test_api_conforms_to_its_openapi_document(case, served):
    case.call_and_validate(
        base_url=served["base_url"],
        headers=served["headers"],
        excluded_checks=EXCLUDED_CHECKS,
    )
