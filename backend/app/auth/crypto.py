"""Password hashing, random secrets and access tokens (ADR-0012).

Passwords: Argon2id. Refresh tokens, session ids, authorization codes and personal access
tokens: 256-bit random secrets with a readable prefix, stored as SHA-256 only. Access
tokens: EdDSA (Ed25519) JWTs with a `kid`, 15 minutes.
"""

import datetime as dt
import hashlib
import hmac
import secrets
import unicodedata
import uuid
from base64 import urlsafe_b64encode
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ACCESS_TOKEN_SECONDS = 15 * 60
REFRESH_TOKEN_DAYS = 90
SESSION_DAYS = 14
AUTH_REQUEST_SECONDS = 10 * 60
ISSUER = AUDIENCE = "opennote"

_hasher = PasswordHasher()  # argon2-cffi's defaults are Argon2id, RFC 9106 low-memory
# Verified against when the user does not exist, so a miss costs as much as a hit.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def username_key(username: str) -> str:
    return unicodedata.normalize("NFC", username).casefold()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
    except Argon2Error:
        return False


def new_secret(prefix: str) -> str:
    """`prefix` + 43 URL-safe characters (256 bits)."""
    return prefix + secrets.token_urlsafe(32)


def secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def csrf_token(session_secret: str) -> str:
    """Derived from the session secret, so a cookie planted by another site cannot match."""
    return hmac.new(session_secret.encode(), b"opennote-csrf", hashlib.sha256).hexdigest()


def pkce_matches(verifier: str, challenge: str) -> bool:
    """RFC 7636 S256: BASE64URL(SHA256(verifier)) without padding equals the challenge."""
    digest = urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
    return hmac.compare_digest(digest.rstrip(b"=").decode(), challenge)


def new_signing_key() -> tuple[str, str]:
    """A new Ed25519 key as (kid, PKCS#8 PEM)."""
    pem = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return secrets.token_hex(8), pem.decode()


def issue_access_token(
    kid: str, private_pem: str, user_id: uuid.UUID, device_id: uuid.UUID, now: dt.datetime
) -> str:
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user_id),
        "dev": str(device_id),
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + ACCESS_TOKEN_SECONDS,
        "jti": str(uuid.uuid7()),
    }
    return jwt.encode(claims, private_pem, algorithm="EdDSA", headers={"kid": kid})


def token_kid(token: str) -> str | None:
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError:
        return None
    return kid if isinstance(kid, str) else None


def verify_access_token(token: str, private_pem: str) -> dict[str, Any] | None:
    """The claims of a valid, unexpired token signed with this key, else None."""
    key = serialization.load_pem_private_key(private_pem.encode(), password=None).public_key()
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key,  # type: ignore[arg-type]
            algorithms=["EdDSA"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "dev"]},
        )
    except jwt.PyJWTError:
        return None
    return claims
