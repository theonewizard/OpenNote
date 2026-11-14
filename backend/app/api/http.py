"""Parameters shared by the v1 endpoints (docs/api/api-contract.md §1).

The precondition and idempotency rules themselves are enforced by the endpoints: a
missing `If-Match` on `PUT`, `PATCH` or `DELETE` is a 428, a stale one a 412.
"""

import uuid
from typing import Annotated

from fastapi import Header, Query

IfMatch = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description='The `ETag` last read, `"<revision>"`. Required: missing is 428, stale is 412',
    ),
]
IdempotencyKey = Annotated[
    uuid.UUID | None,
    Header(
        alias="Idempotency-Key",
        description="Repeating a request with the same key within 24 h returns the first response",
    ),
]
Limit = Annotated[int, Query(ge=1, le=500, description="Page size")]
Cursor = Annotated[str | None, Query(description="`next_cursor` of the previous page")]
VaultIdQuery = Annotated[uuid.UUID, Query(description="The vault to list")]
