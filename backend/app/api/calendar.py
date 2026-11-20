"""Calendar feeds (P6-03): a read-only iCalendar subscription of a vault's dated tasks.

A feed is created by a signed-in user for a vault they can read; calendar apps cannot
send a bearer token, so the feed URL carries its own random token in the query string
(never logged: the web proxy logs the path only, the API logs no access lines). Each
fetch rechecks that the feed's owner can still read the vault (R-P6-015)."""

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete, func, select, update

from app.api.deps import DB, forbidden, not_found, require_vault, vault_role
from app.api.schemas import CalendarFeed, CalendarFeedCreate, CalendarFeedCreated, CalendarFeedList
from app.auth.crypto import new_secret, secret_hash
from app.auth.dependencies import Principal, get_caller
from app.auth.models import User
from app.calendar.ics import FeedTask, calendar
from app.calendar.models import CalendarFeed as FeedRow
from app.core.audit import audit
from app.notes.models import File
from app.tasks.models import TaskRow
from app.vaults.models import Vault

router = APIRouter(prefix="/api/v1", tags=["calendar"])
Caller = Annotated[Principal, Depends(get_caller)]

FEED_PATH = "/api/v1/calendar/tasks.ics"
MAX_EVENTS = 5000


def _model(row: FeedRow) -> CalendarFeed:
    return CalendarFeed(
        id=row.id,
        vault_id=row.vault_id,
        name=row.name,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
    )


@router.post("/calendar-feeds", status_code=201)
async def create_calendar_feed(
    body: CalendarFeedCreate, request: Request, caller: Caller, db: DB
) -> CalendarFeedCreated:
    """Create a feed; the URL with its token is shown once. A personal access token cannot
    create one (it would outlive the token's own limits)."""
    if caller.kind == "api_key" or caller.user_id is None:
        raise forbidden()
    await require_vault(db, caller, body.vault_id, "viewer")
    token = new_secret("onc_")
    row = FeedRow(
        user_id=caller.user_id,
        vault_id=body.vault_id,
        name=body.name,
        token_hash=secret_hash(token),
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    audit(db, request, "calendar_feed.create", caller, vault_id=body.vault_id, target=str(row.id))
    await db.commit()
    return CalendarFeedCreated(feed=_model(row), url=f"{FEED_PATH}?token={token}")


@router.get("/calendar-feeds")
async def list_calendar_feeds(
    caller: Caller, db: DB, vault_id: Annotated[uuid.UUID | None, Query()] = None
) -> CalendarFeedList:
    """The caller's feeds, newest first."""
    query = select(FeedRow).where(FeedRow.user_id == caller.user_id)
    if vault_id is not None:
        query = query.where(FeedRow.vault_id == vault_id)
    rows = await db.scalars(query.order_by(FeedRow.created_at.desc(), FeedRow.id))
    return CalendarFeedList(items=[_model(r) for r in rows])


@router.delete("/calendar-feeds/{feed_id}", status_code=204)
async def delete_calendar_feed(
    feed_id: uuid.UUID, request: Request, caller: Caller, db: DB
) -> None:
    """Revoke a feed: its URL stops working at once."""
    deleted = await db.scalar(
        delete(FeedRow)
        .where(FeedRow.id == feed_id, FeedRow.user_id == caller.user_id)
        .returning(FeedRow.vault_id)
    )
    if deleted is None:
        raise not_found("Calendar feed")
    audit(db, request, "calendar_feed.delete", caller, vault_id=deleted, target=str(feed_id))
    await db.commit()


@router.get(
    "/calendar/tasks.ics",
    response_class=Response,
    responses={200: {"content": {"text/calendar": {"schema": {"type": "string"}}}}},
)
async def get_calendar_feed(
    db: DB,
    token: Annotated[str, Query(min_length=1, max_length=128, description="The feed's token")],
) -> Response:
    """The feed: open tasks with a due date or a reminder, as iCalendar (keyless: the
    token is the credential)."""
    row = await db.scalar(select(FeedRow).where(FeedRow.token_hash == secret_hash(token)))
    user = await db.get(User, row.user_id) if row is not None else None
    vault = await db.get(Vault, row.vault_id) if row is not None else None
    if row is None or user is None or vault is None or user.disabled:
        raise not_found("Calendar feed")
    owner = Principal(id=str(user.id), kind="user", user_id=user.id)
    if await vault_role(db, owner, vault.id) is None:
        raise not_found("Calendar feed")
    rows = await db.execute(
        select(TaskRow, File.path)
        .join(File, File.file_id == TaskRow.file_id)
        .where(
            TaskRow.vault_id == vault.id,
            ~TaskRow.done,
            ~File.deleted,
            (TaskRow.due.is_not(None)) | (TaskRow.remind_at.is_not(None)),
        )
        .order_by(func.coalesce(TaskRow.due, func.date(TaskRow.remind_at)), File.path)
        .limit(MAX_EVENTS)
    )
    tasks = [FeedTask(t.file_id, t.ordinal, t.text, path, t.due, t.remind_at) for t, path in rows]
    await db.execute(update(FeedRow).where(FeedRow.id == row.id).values(last_used_at=func.now()))
    await db.commit()
    body = calendar(f"{vault.name}: {row.name}", tasks, dt.datetime.now(dt.UTC))
    return Response(
        body,
        media_type="text/calendar; charset=utf-8",
        headers={"Cache-Control": "private, max-age=300"},
    )
