"""Tags (P2-07) and search (P2-08). Both are scoped to the caller's vaults before matching."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.http import Cursor, Limit, VaultIdQuery, not_implemented
from app.api.schemas import SearchPage, TagPage
from app.auth.dependencies import Principal, get_caller

router = APIRouter(prefix="/api/v1", tags=["search"])
Caller = Annotated[Principal, Depends(get_caller)]


@router.get("/tags")
async def list_tags(
    caller: Caller, vault_id: VaultIdQuery, cursor: Cursor = None, limit: Limit = 500
) -> TagPage:
    """Tags with their note counts, sorted by name."""
    raise not_implemented()


@router.get("/search")
async def search(
    caller: Caller,
    q: Annotated[str, Query(max_length=1024, description="Query, grammar in API contract §5")],
    vault_id: Annotated[
        uuid.UUID | None, Query(description="One vault; omitted, every vault of the caller")
    ] = None,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> SearchPage:
    """Full-text search with filters, best match first."""
    raise not_implemented()
