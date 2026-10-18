"""RFC 9457 problem details: the response builder and the app's exception handlers.

Clients get a generic, safe `detail`; exceptions are logged server-side only (CLAUDE.md §13).
"""

import logging
from collections.abc import Mapping, Sequence
from http.client import responses as status_phrases
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.utils import is_body_allowed_for_status_code
from starlette.exceptions import HTTPException

PROBLEM_TYPE_BASE = "https://opennote.dev/problems/"
PROBLEM_MEDIA_TYPE = "application/problem+json"
INTERNAL_ERROR_DETAIL = "An internal error occurred. The request ID is in the X-Request-ID header."

# The body problem_response builds, as the OpenAPI document's ProblemDetails schema. detail
# and instance are left out rather than null; extension members such as `errors` are allowed.
PROBLEM_DETAILS_SCHEMA: dict[str, Any] = {
    "title": "ProblemDetails",
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "title": {"type": "string"},
        "status": {"type": "integer"},
        "detail": {"type": "string"},
        "instance": {"type": "string"},
    },
    "required": ["type", "title", "status"],
    "additionalProperties": True,
}

logger = logging.getLogger(__name__)


class ProblemError(HTTPException):
    """An HTTP error that carries its own problem type, title and detail."""

    def __init__(
        self,
        status: int,
        title: str,
        type_slug: str,
        detail: str | None = None,
    ) -> None:
        super().__init__(status_code=status, detail=detail)
        self.title = title
        self.type_slug = type_slug


def problem_response(
    status: int,
    title: str,
    type_slug: str,
    detail: str | None = None,
    instance: str | None = None,
    *,
    extensions: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"type": PROBLEM_TYPE_BASE + type_slug, "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    if instance is not None:
        body["instance"] = instance
    body.update(extensions or {})
    response_headers = dict(headers or {})
    if status == 401:
        response_headers.setdefault("WWW-Authenticate", "Bearer")
    return JSONResponse(
        body, status_code=status, headers=response_headers, media_type=PROBLEM_MEDIA_TYPE
    )


async def handle_http_exception(request: Request, exc: HTTPException) -> Response:
    if not is_body_allowed_for_status_code(exc.status_code):  # 1xx, 204, 205, 304
        return Response(status_code=exc.status_code, headers=exc.headers)
    path = request.url.path
    if isinstance(exc, ProblemError):
        return problem_response(exc.status_code, exc.title, exc.type_slug, exc.detail, path)
    # exc.detail is free text from wherever it was raised; the status phrase is safe.
    detail = status_phrases.get(exc.status_code)
    return problem_response(
        exc.status_code, "HTTP error", "http-error", detail, path, headers=exc.headers
    )


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Built from loc and msg only: pydantic's error also carries the rejected input.
    errors = [{"pointer": _json_pointer(e["loc"]), "message": e["msg"]} for e in exc.errors()]
    return problem_response(
        422,
        "Validation error",
        "validation-error",
        "The request is not valid.",
        request.url.path,
        extensions={"errors": errors},
    )


async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    # Runs outside the request-ID middleware (Starlette's outermost error middleware),
    # so the request ID is taken from request.state and the header is set here.
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "Unhandled exception",
        exc_info=exc,
        extra={"request_id": request_id, "method": request.method, "path": request.url.path},
    )
    response = problem_response(
        500, "Internal error", "internal-error", INTERNAL_ERROR_DETAIL, request.url.path
    )
    if request_id is not None:
        response.headers["X-Request-ID"] = request_id
    return response


def _json_pointer(loc: Sequence[str | int]) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in loc)
