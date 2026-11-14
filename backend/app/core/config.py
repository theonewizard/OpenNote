"""Settings from OPENNOTE_* environment variables; secrets may come from <NAME>_FILE instead."""

import logging
import os
import re
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    Field,
    PostgresDsn,
    RedisDsn,
    TypeAdapter,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "OPENNOTE_"
# Read from the file named by OPENNOTE_<FIELD>_FILE when OPENNOTE_<FIELD> is unset or empty.
SECRET_FIELDS = ("database_url", "valkey_url")
MAX_SECRET_FILE_BYTES = 64 * 1024


class SettingsError(Exception):
    """Invalid or missing settings. The message names fields only, never their values."""


class OidcProvider(BaseModel):
    """An upstream OpenID Connect provider (R-P2-006). The client secret comes from
    OPENNOTE_OIDC_<NAME>_CLIENT_SECRET_FILE unless given directly."""

    model_config = {"frozen": True}

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    issuer: str
    client_id: str = Field(min_length=1)
    client_secret: str = Field(default="", repr=False)

    @field_validator("issuer")
    @classmethod
    def _https_issuer(cls, value: str) -> str:
        url = urlsplit(value)
        local = url.hostname in {"127.0.0.1", "localhost"}
        if not url.hostname or (url.scheme != "https" and not (url.scheme == "http" and local)):
            raise ValueError("issuer must be an https URL")
        return value

    @model_validator(mode="before")
    @classmethod
    def _secret_from_file(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("client_secret"):
            name = re.sub(r"[^A-Za-z0-9]", "_", str(data.get("name", ""))).lower()
            field = f"oidc_{name}_client_secret"
            path = os.environ.get(ENV_PREFIX + field.upper() + "_FILE")
            if not path:
                raise SettingsError(f"invalid or missing settings: {field}")
            data = data | {"client_secret": _read_secret_file(path, field)}
        return data


class Settings(BaseSettings):
    """Process settings. The URLs carry credentials, so repr() and str() leave them out;
    model_dump() is an explicit call that includes them and must never be logged."""

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, frozen=True)

    database_url: PostgresDsn = Field(
        repr=False,
        description="SQLAlchemy URL for psycopg 3: "
        "postgresql+psycopg://<user>:<password>@<host>:5432/<database>",
    )
    valkey_url: RedisDsn = Field(
        repr=False, description="Valkey speaks RESP: redis://<host>:6379/0"
    )
    vault_root: Path = Field(description="Directory holding the vaults")
    history_root: Path = Field(description="Directory holding note history")
    max_blob_bytes: int = Field(
        default=512 * 1024 * 1024, ge=1, description="Largest attachment upload, in bytes"
    )
    # Retention (design D6, sync protocol §2.1, P5-07); the vault watcher applies it daily.
    history_keep_all_days: int = Field(30, ge=1, description="Every revision is kept this long")
    history_keep_daily_days: int = Field(
        365, ge=1, description="Then the last revision of each day, until this age"
    )
    tombstone_retention_days: int = Field(
        90,
        ge=8,  # clients drop outbox operations 7 days before this window ends
        description="Deletes and operation results are kept this long",
    )
    log_level: str = "INFO"
    environment: Literal["development", "test", "production"] = "production"
    # Requests per minute under /api/ (app.api.ratelimit); 0 turns that limit off.
    rate_limit_per_principal: int = Field(600, ge=0)
    rate_limit_per_ip: int = Field(1200, ge=0)
    rate_limit_auth_per_ip: int = Field(10, ge=0)
    oidc_providers: list[OidcProvider] = Field(
        default=[], description='JSON list of {"name", "issuer", "client_id"}'
    )

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        level = value.upper()
        # NOTSET on the root logger would pass every record, library debug output included.
        if level == "NOTSET" or level not in logging.getLevelNamesMapping():
            raise ValueError("unknown log level")
        return level

    @field_validator("history_keep_daily_days")
    @classmethod
    def _daily_after_all(cls, value: int, info: ValidationInfo) -> int:
        if value < info.data.get("history_keep_all_days", 0):
            raise ValueError("must not be below history_keep_all_days")
        return value


def _secrets_from_files(fields: Iterable[str] = SECRET_FIELDS) -> dict[str, Any]:
    secrets: dict[str, Any] = {}
    for field in fields:
        variable = ENV_PREFIX + field.upper()
        path = os.environ.get(variable + "_FILE")
        if path and not os.environ.get(variable):
            secrets[field] = _read_secret_file(path, field)
    return secrets


def _read_secret_file(path: str, field: str) -> str:
    try:
        with Path(path).open("rb") as file:
            data = file.read(MAX_SECRET_FILE_BYTES + 1)
        if len(data) <= MAX_SECRET_FILE_BYTES:
            return data.decode("utf-8").removesuffix("\n")
    except OSError, UnicodeDecodeError:
        pass
    # Raised outside the except block so the OSError, which names the path, is not chained.
    raise SettingsError(
        f"invalid or missing settings: {field} "
        f"(secret file unreadable, not UTF-8 or larger than {MAX_SECRET_FILE_BYTES // 1024} KiB)"
    )


def load_settings() -> Settings:
    """Build settings from the environment, uncached; raise SettingsError if invalid."""
    try:
        return Settings(**_secrets_from_files())
    except ValidationError as exc:
        fields = sorted({".".join(map(str, error["loc"])) for error in exc.errors()})
    # Raised outside the except block: pydantic's error echoes input values (passwords).
    raise SettingsError("invalid or missing settings: " + ", ".join(fields))


def load_database_url() -> str:
    """Only the database URL, for migrations: OPENNOTE_DATABASE_URL or its _FILE, validated
    as Settings.database_url is; raise SettingsError naming the field, never the value."""
    value = _secrets_from_files(["database_url"]).get("database_url") or os.environ.get(
        ENV_PREFIX + "DATABASE_URL"
    )
    try:
        return str(TypeAdapter(PostgresDsn).validate_python(value))
    except ValidationError:
        pass
    # Raised outside the except block: pydantic's error echoes input values (passwords).
    raise SettingsError("invalid or missing settings: database_url")


@cache
def get_settings() -> Settings:
    """The process-wide settings, loaded once."""
    return load_settings()
