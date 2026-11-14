"""Rate limits (Phase 2 Task 8): fixed one-minute windows in Valkey, per IP and per
credential, stricter on the sign-in routes."""

import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import anyio
import pytest
from httpx2 import ASGITransport, AsyncClient
from redis.asyncio import Redis

from app.api.main import create_app
from app.core.config import Settings

pytestmark = pytest.mark.anyio

RATE_HEADERS = ("ratelimit-limit", "ratelimit-remaining", "ratelimit-reset")


@pytest.fixture(autouse=True)
async def fresh_window(valkey_url: str) -> None:
    """Delete the counters and keep clear of a window boundary, so a test's requests
    all fall into one window."""
    async with Redis.from_url(valkey_url) as valkey:
        keys = [key async for key in valkey.scan_iter("ratelimit:*")]
        if keys:
            await valkey.delete(*keys)
    if 60 - time.time() % 60 < 3:
        await anyio.sleep(60 - time.time() % 60 + 0.1)


@pytest.fixture
def limited(make_settings: Callable[..., Settings]) -> Callable[..., Any]:
    """An app with the given limits; `client(ip)` opens a client calling from that address."""

    @asynccontextmanager
    async def build(**limits: Any) -> AsyncIterator[Callable[[str], AsyncClient]]:
        app = create_app(make_settings(**limits))
        async with app.router.lifespan_context(app):

            def client(ip: str = "192.0.2.1") -> AsyncClient:
                transport = ASGITransport(app=app, client=(ip, 4000))
                return AsyncClient(transport=transport, base_url="http://test")

            yield client

    return build


async def test_over_the_ip_limit_is_429_with_headers(limited):
    async with limited(rate_limit_per_ip=2) as client, client() as c:
        first = await c.get("/api/v1/meta")
        assert first.status_code == 200
        assert first.headers["ratelimit-limit"] == "2"
        assert first.headers["ratelimit-remaining"] == "1"
        assert 0 < int(first.headers["ratelimit-reset"]) <= 60
        assert (await c.get("/api/v1/meta")).headers["ratelimit-remaining"] == "0"

        response = await c.get("/api/v1/meta", headers={"X-Request-ID": "req-429"})
    assert response.status_code == 429
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"].endswith("/rate-limited")
    assert response.json()["status"] == 429
    assert response.headers["x-request-id"] == "req-429"
    assert response.headers["ratelimit-limit"] == "2"
    assert response.headers["ratelimit-remaining"] == "0"
    reset = int(response.headers["ratelimit-reset"])
    assert 0 < reset <= 60
    assert response.headers["retry-after"] == str(reset)


async def test_each_ip_has_its_own_counter(limited):
    async with (
        limited(rate_limit_per_ip=1) as client,
        client("192.0.2.1") as a,
        client("192.0.2.2") as b,
    ):
        assert (await a.get("/api/v1/meta")).status_code == 200
        assert (await a.get("/api/v1/meta")).status_code == 429
        assert (await b.get("/api/v1/meta")).status_code == 200


@pytest.mark.usefixtures("engine")  # the session cookie is looked up
async def test_each_credential_has_its_own_counter(limited):
    """Counted before authentication, so even invalid credentials are counted (401)."""
    async with limited(rate_limit_per_principal=2) as client, client() as c:
        alice = {"Authorization": "Bearer token-of-alice"}
        bob = {"X-API-Key": "onp_key-of-bob"}
        carol = {"Cookie": "opennote_session=session-of-carol"}
        for _ in range(2):
            assert (await c.get("/api/v1/me", headers=alice)).status_code == 401
        limited_response = await c.get("/api/v1/me", headers=alice)
        assert limited_response.status_code == 429
        assert limited_response.headers["ratelimit-limit"] == "2"
        assert (await c.get("/api/v1/me", headers=bob)).status_code == 401
        assert (await c.get("/api/v1/me", headers=carol)).status_code == 401
        # Without a credential only the per-IP limit (unlimited here) applies.
        assert (await c.get("/api/v1/meta")).status_code == 200


async def test_raw_credentials_are_not_stored(limited, valkey_url):
    async with limited(rate_limit_per_principal=5) as client, client() as c:
        await c.get("/api/v1/me", headers={"Authorization": "Bearer very-secret-token"})
    async with Redis.from_url(valkey_url) as valkey:
        keys = [key async for key in valkey.scan_iter("ratelimit:*")]
    assert len(keys) == 1
    assert b"very-secret-token" not in keys[0]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/token"),
        ("GET", "/api/v1/auth/authorize"),
        ("GET", "/api/v1/auth/oidc/corp/callback"),
    ],
)
async def test_sign_in_routes_have_a_stricter_ip_limit(limited, method, path):
    async with limited(rate_limit_per_ip=100, rate_limit_auth_per_ip=2) as client, client() as c:
        for _ in range(2):
            assert (await c.request(method, path)).status_code != 429
        response = await c.request(method, path)
        assert response.status_code == 429
        assert response.headers["ratelimit-limit"] == "2"
        # Other routes still have the general limit.
        assert (await c.get("/api/v1/meta")).status_code == 200


async def test_health_probes_are_never_limited(limited):
    async with limited(rate_limit_per_ip=1) as client, client() as c:
        for _ in range(3):
            response = await c.get("/healthz")
            assert response.status_code == 200
            assert "ratelimit-limit" not in response.headers


async def test_requests_pass_when_valkey_is_down(limited, caplog):
    dead = "redis://127.0.0.1:9/6"  # nothing listens on port 9
    async with limited(valkey_url=dead, rate_limit_per_ip=1) as client, client() as c:
        for _ in range(3):
            response = await c.get("/api/v1/meta")
            assert response.status_code == 200
            assert all(name not in response.headers for name in RATE_HEADERS)
    warnings = [r for r in caplog.records if "rate limit" in r.getMessage().lower()]
    assert len(warnings) == 1  # at most once a minute
