"""ETag preconditions, cursors and idempotent replay (P2-01)."""

import uuid

import pytest
from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.conventions import (
    check_if_match,
    decode_cursor,
    encode_cursor,
    etag,
    remember,
    replay,
    request_hash,
)
from app.auth.dependencies import Principal
from app.core.problems import ProblemError

pytestmark = pytest.mark.anyio


def test_if_match_missing_is_428_and_stale_is_412_with_current():
    with pytest.raises(ProblemError) as missing:
        check_if_match(None, 3, {"revision": 3})
    assert missing.value.status_code == 428
    with pytest.raises(ProblemError) as stale:
        check_if_match('"2"', 3, {"revision": 3})
    assert stale.value.status_code == 412
    assert stale.value.extensions == {"current": {"revision": 3}}
    assert stale.value.headers == {"ETag": '"3"'}
    check_if_match('"3"', 3, {})
    check_if_match('W/"3", "9"', 3, {})
    assert etag(7) == '"7"'


def test_cursor_round_trip_and_rejection():
    cursor = encode_cursor(["Work/a.md", "0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c"])
    assert decode_cursor(cursor, 2) == ["Work/a.md", "0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c"]
    assert decode_cursor(None, 2) is None
    for bad in ["!!", encode_cursor([1]), "e30"]:
        with pytest.raises(ProblemError) as err:
            decode_cursor(bad, 2)
        assert err.value.status_code == 400


async def test_idempotent_replay(api):
    alice = api.user("alice")
    principal = Principal(id=str(alice.id), kind="user", user_id=alice.id)
    key = uuid.uuid4()
    first = request_hash("POST", "/api/v1/notes", b'{"a":1}')
    async with AsyncSession(api.app.state.engine) as db:
        assert await replay(db, principal, key, first) is None
        sent = Response(
            b'{"id":1}', status_code=201, headers={"ETag": '"1"'}, media_type="application/json"
        )
        await remember(db, principal, key, first, sent)
        again = await replay(db, principal, key, first)
        assert again is not None
        assert (again.status_code, again.body, again.headers["etag"]) == (201, b'{"id":1}', '"1"')
        with pytest.raises(ProblemError) as reused:
            await replay(db, principal, key, request_hash("POST", "/api/v1/notes", b'{"a":2}'))
        assert reused.value.status_code == 422
        other = Principal(id="x", kind="user", user_id=uuid.uuid4())
        assert await replay(db, other, key, first) is None  # keys are per principal
