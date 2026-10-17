"""Liveness and readiness probes (keyless). The body says only ok or fail."""

import asyncio
import logging
import os
from collections.abc import Awaitable
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings

router = APIRouter()
logger = logging.getLogger(__name__)


class ProbeStatus(BaseModel):
    status: Literal["ok", "fail"]


@router.get("/healthz")
async def healthz() -> ProbeStatus:
    return ProbeStatus(status="ok")


@router.get("/readyz", responses={503: {"model": ProbeStatus}})
async def readyz(request: Request, response: Response) -> ProbeStatus:
    """Ready when PostgreSQL and Valkey answer and both data directories are writable.

    The checks run concurrently, each under its own timeout, so the probe answers in
    about one timeout even when a host is unreachable.
    """
    settings: Settings = request.app.state.settings
    checks = await asyncio.gather(
        check_database(request.app.state.engine),
        check_valkey(str(settings.valkey_url)),
        check_directory("vault_root", settings.vault_root),
        check_directory("history_root", settings.history_root),
    )
    if all(checks):
        return ProbeStatus(status="ok")
    response.status_code = 503
    return ProbeStatus(status="fail")


# Each check owns its timeout (hence noqa ASYNC109): readyz runs them side by side and a
# slow dependency must fail its own check, not the whole probe.
async def check_database(engine: AsyncEngine, timeout: float = 2.0) -> bool:  # noqa: ASYNC109
    """True when SELECT 1 through the engine succeeds within `timeout` seconds."""
    return await _passes("database", _select_one(engine), timeout)


async def check_valkey(url: str, timeout: float = 2.0) -> bool:  # noqa: ASYNC109
    """True when Valkey answers PING within `timeout` seconds; the client lives for one call."""
    async with Redis.from_url(url, socket_connect_timeout=timeout) as client:
        return await _passes("valkey", client.ping(), timeout)


async def check_directory(check: str, path: Path, timeout: float = 2.0) -> bool:  # noqa: ASYNC109
    """True when `path` is a directory this process may create files in."""
    return await _passes(check, asyncio.to_thread(_is_writable_directory, path), timeout)


async def _select_one(engine: AsyncEngine) -> bool:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return True


def _is_writable_directory(path: Path) -> bool:
    # Runs in a thread: a stat on a hung network mount must not block the event loop.
    return path.is_dir() and os.access(path, os.W_OK | os.X_OK)


async def _passes(check: str, probe: Awaitable[bool], seconds: float) -> bool:
    """Await the probe for up to `seconds`. A failure is logged by check name and exception
    type only: exception messages can name hosts, paths or credentials."""
    error = None
    try:
        if await asyncio.wait_for(probe, seconds):
            return True
    except Exception as exc:  # whatever the cause, the dependency is not ready
        error = type(exc).__name__
    logger.warning("Readiness check failed", extra={"check": check, "error": error})
    return False
