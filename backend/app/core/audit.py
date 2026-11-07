"""The append-only audit log (design §8): authentication events, ACL changes, deletes,
admin actions. Never holds a secret or note content."""

import datetime as dt
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.dependencies import Principal
from app.core.db import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    action: Mapped[str]
    actor_user_id: Mapped[uuid.UUID | None]
    actor_device: Mapped[str | None]
    vault_id: Mapped[uuid.UUID | None]
    target: Mapped[str | None]
    ip: Mapped[str | None]
    request_id: Mapped[str | None]
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


def audit(
    db: AsyncSession,
    request: Request,
    action: str,
    principal: Principal | None = None,
    *,
    user_id: uuid.UUID | None = None,
    vault_id: uuid.UUID | None = None,
    target: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an event to the session; it is written with the caller's commit, so an action
    and its record succeed or fail together. `action` is dotted: `auth.login`,
    `auth.login_failed`, `vault.member_put`, `note.delete`, ..."""
    db.add(
        AuditEvent(
            action=action,
            actor_user_id=principal.user_id if principal else user_id,
            actor_device=principal.device_id if principal else None,
            vault_id=vault_id,
            target=target,
            ip=request.client.host if request.client else None,
            request_id=getattr(request.state, "request_id", None),
            details=details or {},
        )
    )
