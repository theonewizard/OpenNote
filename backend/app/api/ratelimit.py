"""Rate limits under /api/: fixed one-minute windows counted in Valkey, per client IP and
per credential, with a stricter per-IP limit on the sign-in routes. Counted before
routing and authentication, so failed sign-ins and bad credentials count too."""

import hashlib
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.auth.dependencies import SESSION_COOKIE
from app.core.config import Settings
from app.core.problems import problem_response

WINDOW = 60  # seconds
AUTH_PATHS = ("/api/v1/auth/login", "/api/v1/auth/token", "/api/v1/auth/authorize")
AUTH_PREFIX = "/api/v1/auth/oidc/"

logger = logging.getLogger(__name__)


def _credential(request: Request) -> str | None:
    value = (
        request.headers.get("Authorization")
        or request.headers.get("X-API-Key")
        or request.cookies.get(SESSION_COOKIE)
    )
    # A digest names the counter: the raw secret never reaches Valkey.
    return hashlib.sha256(value.encode()).hexdigest()[:32] if value else None


def _limits(request: Request, settings: Settings) -> list[tuple[str, int]]:
    """(counter name, limit) of every limit that applies; a limit of 0 is off."""
    path = request.url.path
    ip = request.client.host if request.client else "unknown"
    limits = [(f"ip:{ip}", settings.rate_limit_per_ip)]
    if path in AUTH_PATHS or path.startswith(AUTH_PREFIX):
        limits.append((f"auth:{ip}", settings.rate_limit_auth_per_ip))
    if credential := _credential(request):
        limits.append((f"cred:{credential}", settings.rate_limit_per_principal))
    return [(name, limit) for name, limit in limits if limit > 0]


async def rate_limit_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if not request.url.path.startswith("/api/"):
        return await call_next(request)  # health probes and anything else outside the API
    limits = _limits(request, request.app.state.settings)
    if not limits:
        return await call_next(request)
    now = time.time()
    window = int(now // WINDOW)
    reset = WINDOW - int(now % WINDOW)
    valkey: Redis = request.app.state.valkey
    try:
        async with valkey.pipeline(transaction=True) as pipe:
            for name, _ in limits:
                key = f"ratelimit:{name}:{window}"
                pipe.incr(key)
                pipe.expire(key, WINDOW)
            counts = (await pipe.execute())[::2]
    except RedisError, OSError:
        # Fail open: with Valkey down every request would otherwise be refused, so the
        # limits are skipped instead, with a warning at most once a minute. /readyz
        # reports Valkey as down meanwhile.
        if now - request.app.state.ratelimit_warned_at >= WINDOW:
            request.app.state.ratelimit_warned_at = now
            logger.warning("Rate limits not applied: Valkey unreachable")
        return await call_next(request)
    # Report the limit closest to running out.
    limit, count = min(
        ((limit, count) for (_, limit), count in zip(limits, counts, strict=True)),
        key=lambda pair: pair[0] - pair[1],
    )
    headers = {
        "RateLimit-Limit": str(limit),
        "RateLimit-Remaining": str(max(limit - count, 0)),
        "RateLimit-Reset": str(reset),
    }
    if count > limit:
        return problem_response(
            429,
            "Too many requests",
            "rate-limited",
            "Rate limit exceeded; retry after the number of seconds in Retry-After.",
            request.url.path,
            headers=headers | {"Retry-After": str(reset)},
        )
    response = await call_next(request)
    response.headers.update(headers)
    return response
