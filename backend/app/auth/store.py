"""Credential store operations shared by the auth endpoints, the admin command and tests."""

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import (
    ACCESS_TOKEN_SECONDS,
    REFRESH_TOKEN_DAYS,
    SESSION_DAYS,
    csrf_token,
    issue_access_token,
    new_secret,
    new_signing_key,
    secret_hash,
)
from app.auth.models import Device, RefreshToken, SigningKey, User, WebSession


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def signing_key(db: AsyncSession) -> SigningKey:
    """The newest active signing key, created on first use (R-P2-003). Two processes
    racing here each create a key; both stay valid, the newest signs."""
    key = await db.scalar(
        select(SigningKey)
        .where(SigningKey.retired_at.is_(None))
        .order_by(SigningKey.created_at.desc(), SigningKey.kid)
        .limit(1)
    )
    if key is None:
        kid, pem = new_signing_key()
        key = SigningKey(kid=kid, private_pem=pem)
        db.add(key)
        await db.flush()
    return key


async def issue_device_tokens(db: AsyncSession, device: Device) -> tuple[str, int, str]:
    """A new access token and refresh token for the device: (access, expires_in, refresh).
    The caller commits."""
    key = await signing_key(db)
    issued = now()
    access = issue_access_token(key.kid, key.private_pem, device.user_id, device.id, issued)
    refresh = new_secret("onr_")
    db.add(
        RefreshToken(
            device_id=device.id,
            token_hash=secret_hash(refresh),
            expires_at=issued + dt.timedelta(days=REFRESH_TOKEN_DAYS),
        )
    )
    device.last_seen_at = issued
    return access, ACCESS_TOKEN_SECONDS, refresh


async def create_device(
    db: AsyncSession, user_id: uuid.UUID, name: str, platform: str | None
) -> Device:
    device = Device(id=uuid.uuid7(), user_id=user_id, name=name, platform=platform)
    db.add(device)
    await db.flush()
    return device


async def create_session(db: AsyncSession, user: User) -> tuple[str, str, dt.datetime]:
    """A new web session: (cookie secret, CSRF token, expiry). The caller commits."""
    secret = new_secret("ons_")
    expires = now() + dt.timedelta(days=SESSION_DAYS)
    db.add(WebSession(user_id=user.id, token_hash=secret_hash(secret), expires_at=expires))
    return secret, csrf_token(secret), expires
