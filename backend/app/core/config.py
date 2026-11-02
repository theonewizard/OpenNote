"""Settings from OPENNOTE_* environment variables; secrets may come from <NAME>_FILE instead."""

import logging
import os
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, PostgresDsn, RedisDsn, TypeAdapter, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "OPENNOTE_"
# Read from the file named by OPENNOTE_<FIELD>_FILE when OPENNOTE_<FIELD> is unset or empty.
SECRET_FIELDS = ("database_url", "valkey_url")
MAX_SECRET_FILE_BYTES = 64 * 1024


class SettingsError(Exception):
    """Invalid or missing settings. The message names fields only, never their values."""


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
    log_level: str = "INFO"
    environment: Literal["development", "test", "production"] = "production"

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        level = value.upper()
        # NOTSET on the root logger would pass every record, library debug output included.
        if level == "NOTSET" or level not in logging.getLevelNamesMapping():
            raise ValueError("unknown log level")
        return level


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
