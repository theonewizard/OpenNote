"""Attachment endpoints (P2-06): upload with server-side type sniffing, Range download."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response

from app.api.http import Cursor, IdempotencyKey, IfMatch, Limit, VaultIdQuery, not_implemented
from app.api.schemas import Attachment, AttachmentPage
from app.auth.dependencies import Principal, get_caller

router = APIRouter(prefix="/api/v1/attachments", tags=["attachments"])
Caller = Annotated[Principal, Depends(get_caller)]

_ETAG = {"ETag": {"description": 'The revision, `"<revision>"`', "schema": {"type": "string"}}}
_BYTES = {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}


@router.get("")
async def list_attachments(
    caller: Caller,
    vault_id: VaultIdQuery,
    folder: Annotated[str | None, Query(max_length=1024)] = None,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> AttachmentPage:
    raise not_implemented()


@router.post("", status_code=201, responses={201: {"headers": _ETAG}})
async def upload_attachment(
    caller: Caller,
    vault_id: Annotated[uuid.UUID, Form()],
    path: Annotated[str, Form(min_length=1, max_length=1024)],
    file: Annotated[UploadFile, File()],
    idempotency_key: IdempotencyKey = None,
) -> Attachment:
    """Upload a new attachment (multipart). The stored `media_type` is sniffed from the
    bytes; the declared type is ignored. An existing path is a 409."""
    raise not_implemented()


@router.get("/{attachment_id}", responses={200: {"headers": _ETAG}})
async def get_attachment(attachment_id: uuid.UUID, caller: Caller) -> Attachment:
    raise not_implemented()


@router.delete("/{attachment_id}", status_code=204)
async def delete_attachment(
    attachment_id: uuid.UUID, caller: Caller, if_match: IfMatch = None
) -> None:
    raise not_implemented()


@router.get(
    "/{attachment_id}/content",
    response_class=Response,
    responses={
        200: {"content": _BYTES, "headers": _ETAG},
        206: {"description": "The requested byte range", "content": _BYTES},
        416: {"description": "Range not satisfiable"},
    },
)
async def get_attachment_content(attachment_id: uuid.UUID, caller: Caller) -> Response:
    """The bytes, with `Range` support (one range) and `Content-Type` as sniffed; served
    with `X-Content-Type-Options: nosniff` and as a download unless it is an image, PDF,
    audio or video file."""
    raise not_implemented()
