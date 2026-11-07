"""ORM models for the credential store (migration 0006, ADR-0012). Secrets are stored
as hashes only: Argon2id for passwords, SHA-256 for random tokens."""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import DateTime, ForeignKey, LargeBinary, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.core.db import Base

Timestamp = DateTime(timezone=True)


def _created() -> Mapped[dt.datetime]:
    return mapped_column(Timestamp, server_default=func.now())


def _user_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    username: Mapped[str]
    username_key: Mapped[str] = mapped_column(unique=True)  # NFC + casefold
    display_name: Mapped[str]
    email: Mapped[str | None]
    password_hash: Mapped[str | None]
    oidc_issuer: Mapped[str | None]
    oidc_subject: Mapped[str | None]
    is_admin: Mapped[bool] = mapped_column(default=False)
    disabled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = _created()


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = _user_fk()
    name: Mapped[str]
    platform: Mapped[str | None]
    created_at: Mapped[dt.datetime] = _created()
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(Timestamp)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(Timestamp)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[dt.datetime] = _created()
    expires_at: Mapped[dt.datetime] = mapped_column(Timestamp)
    used_at: Mapped[dt.datetime | None] = mapped_column(Timestamp)


class WebSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = _user_fk()
    token_hash: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[dt.datetime] = _created()
    expires_at: Mapped[dt.datetime] = mapped_column(Timestamp)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(Timestamp)


class PersonalAccessToken(Base):
    __tablename__ = "personal_access_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = _user_fk()
    name: Mapped[str]
    token_hash: Mapped[str] = mapped_column(unique=True)
    scope: Mapped[str]
    vault_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid()))
    created_at: Mapped[dt.datetime] = _created()
    expires_at: Mapped[dt.datetime | None] = mapped_column(Timestamp)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(Timestamp)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(Timestamp)


class SigningKey(Base):
    __tablename__ = "signing_keys"

    kid: Mapped[str] = mapped_column(primary_key=True)
    private_pem: Mapped[str]
    created_at: Mapped[dt.datetime] = _created()
    retired_at: Mapped[dt.datetime | None] = mapped_column(Timestamp)


class AuthRequest(Base):
    """A pending OAuth authorization request, then its single-use code."""

    __tablename__ = "auth_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    client_id: Mapped[str]
    redirect_uri: Mapped[str]
    code_challenge: Mapped[str]
    state: Mapped[str]
    provider: Mapped[str | None]
    oidc_state: Mapped[str | None] = mapped_column(unique=True)
    oidc_nonce: Mapped[str | None]
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code_hash: Mapped[str | None] = mapped_column(unique=True)
    created_at: Mapped[dt.datetime] = _created()
    expires_at: Mapped[dt.datetime] = mapped_column(Timestamp)
    used_at: Mapped[dt.datetime | None] = mapped_column(Timestamp)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    principal: Mapped[str] = mapped_column(primary_key=True)
    key: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    request_hash: Mapped[str]
    status: Mapped[int]
    headers: Mapped[dict[str, Any]] = mapped_column(JSONB)
    body: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[dt.datetime] = _created()
