"""The API app factory and the deny-by-default route guard (CLAUDE.md §12).

Run with `uvicorn app.api.main:app`.
"""

import re
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.dependencies.models import Dependant
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute, iter_route_contexts
from starlette.exceptions import HTTPException

from app import __version__
from app.api import health, meta
from app.auth.dependencies import get_api_key, get_current_principal
from app.core.config import Settings, SettingsError, get_settings
from app.core.db import engine_from_settings
from app.core.logging import configure_logging, request_id_var
from app.core.problems import (
    handle_http_exception,
    handle_unhandled_exception,
    handle_validation_error,
)

ROUTERS: list[APIRouter] = [health.router, meta.router]

# The only routes callable without credentials; adding one needs review (API contract §2).
KEYLESS_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {("GET", "/healthz"), ("GET", "/readyz"), ("GET", "/api/v1/meta")}
)

_AUTH_DEPENDENCIES = (get_current_principal, get_api_key)
_VALID_REQUEST_ID = re.compile(r"[\x20-\x7e]{1,128}")  # printable ASCII


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API app without doing I/O. Raises RuntimeError for unauthenticated routes."""
    if settings is None:
        settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="OpenNote API",
        version=__version__,
        # No interactive docs or live spec route; the OpenAPI document comes from app.openapi().
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
        exception_handlers={
            HTTPException: handle_http_exception,
            RequestValidationError: handle_validation_error,
            Exception: handle_unhandled_exception,
        },
    )
    app.state.settings = settings
    app.middleware("http")(_request_id_middleware)
    for router in ROUTERS:
        app.include_router(router)
    assert_routes_authenticated(app)
    return app


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Hold the database engine for the app's lifetime and close its pool on shutdown."""
    app.state.engine = engine_from_settings(app.state.settings)
    try:
        yield
    finally:
        await app.state.engine.dispose()


def assert_routes_authenticated(app: FastAPI) -> None:
    """Raise RuntimeError naming every route that has no auth dependency and is not keyless."""
    offending: list[str] = []
    # iter_route_contexts resolves included routers into effective routes, the same walk
    # FastAPI's OpenAPI generator does, so router-level dependencies count.
    for route in iter_route_contexts(app.routes):
        if not isinstance(route.original_route, APIRoute):
            # Not a FastAPI route, so it cannot carry an auth dependency.
            offending.append(f"{type(route.original_route).__name__} {route.path}")
        elif not _has_auth_dependency(route.dependant):
            offending += [
                f"{method} {route.path}"
                for method in sorted(route.methods or ())
                if (method, route.path) not in KEYLESS_ROUTES
            ]
    # FastAPI 0.143 keeps app.frontend(...) and router.frontend(...) routes in private
    # "low priority" lists outside app.routes, where iter_route_contexts does not look.
    # The router's own iterator also yields those of included routers. Fail closed on all.
    for frontend in app.router._iter_low_priority_routes():
        group = getattr(frontend, "original_route", frontend)
        paths = [route.path for route in getattr(group, "routes", [])]
        offending.append("frontend " + (", ".join(paths) or type(group).__name__))
    if offending:
        raise RuntimeError("Routes without an auth dependency: " + ", ".join(offending))


def _has_auth_dependency(dependant: Dependant) -> bool:
    return any(
        sub.call in _AUTH_DEPENDENCIES or _has_auth_dependency(sub)
        for sub in dependant.dependencies
    )


async def _request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Keep a sane inbound X-Request-ID or make one; expose it to logs and echo it."""
    inbound = request.headers.get("X-Request-ID", "")
    request_id = inbound if _VALID_REQUEST_ID.fullmatch(inbound) else str(uuid.uuid4())
    request.state.request_id = request_id
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = request_id
    return response


try:
    app = create_app()
except SettingsError as exc:
    # One line on stderr and exit status 1; the message names fields, never values.
    sys.exit(f"OpenNote cannot start: {exc}")
