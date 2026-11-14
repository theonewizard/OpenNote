"""audit() records who did what from where, with the request's ID (Phase 2 Task 8).
That the table is append-only is tested in test_auth_core.py."""

import uuid
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB
from app.api.main import create_app
from app.auth.dependencies import Principal, get_current_principal
from app.auth.models import Device
from app.core.audit import AuditEvent, audit
from tests.integration.api.conftest import Api
from tests.integration.conftest import serve

pytestmark = pytest.mark.anyio

router = APIRouter()


@router.post("/api/v1/test-audit", status_code=204)
async def audited(
    request: Request,
    principal: Annotated[Principal, Depends(get_current_principal)],
    db: DB,
) -> None:
    audit(db, request, "test.action", principal, target="Notes/a.md", details={"n": 1})
    await db.commit()


@pytest.fixture
async def audit_api(api, monkeypatch):
    from app.api import main

    monkeypatch.setattr(main, "ROUTERS", [*main.ROUTERS, router])
    app = create_app(api.settings)
    async with serve(app) as client:
        yield Api(app, client, api.engine, api.settings)


async def test_audit_records_actor_ip_and_request_id(audit_api):
    alice = audit_api.user("alice")
    headers = await audit_api.bearer(alice) | {"X-Request-ID": "req-audit-1"}
    response = await audit_api.client.post("/api/v1/test-audit", headers=headers)
    assert response.status_code == 204

    with Session(audit_api.engine) as s:
        event = s.scalars(select(AuditEvent).where(AuditEvent.action == "test.action")).one()
        device_id = s.scalars(select(Device.id).where(Device.user_id == alice.id)).one()
    assert event.actor_user_id == alice.id
    assert event.actor_device == str(device_id)
    assert event.ip == "127.0.0.1"  # the ASGI test client's address
    assert event.request_id == "req-audit-1"
    assert event.target == "Notes/a.md"
    assert event.details == {"n": 1}
    assert event.at is not None
    assert isinstance(event.id, uuid.UUID)


async def test_rejected_request_writes_no_event(audit_api):
    response = await audit_api.client.post("/api/v1/test-audit")
    assert response.status_code == 401
    with Session(audit_api.engine) as s:
        assert s.scalars(select(AuditEvent).where(AuditEvent.action == "test.action")).all() == []
