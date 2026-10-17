"""Settings from OPENNOTE_* environment variables; secrets may come from <NAME>_FILE instead."""

import logging
import os
from functools import cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, PostgresDsn, RedisDsn, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "OPENNOTE_"
# Read from the file named by OPENNOTE_<FIELD>_FILE when OPENNOTE_<FIELD> is unset.
SECRET_FIELDS = ("database_url", "valkey_url")


class SettingsError(Exception):
    """Invalid or missing settings. The message names fields only, never their values."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, frozen=True)

    database_url: PostgresDsn = Field(
        description="SQLAlchemy URL for psycopg 3: "
        "postgresql+psycopg://<user>:<password>@<host>:5432/<database>"
    )
    valkey_url: RedisDsn = Field(description="Valkey speaks RESP: redis://<host>:6379/0")
    vault_root: Path = Field(description="Directory holding the vaults")
    history_root: Path = Field(description="Directory holding note history")
    log_level: str = "INFO"
    environment: Literal["development", "test", "production"]

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in logging.getLevelNamesMapping():
            raise ValueError("unknown log level")
        return level


def _secrets_from_files() -> dict[str, Any]:
    secrets: dict[str, Any] = {}
    for field in SECRET_FIELDS:
        variable = ENV_PREFIX + field.upper()
        path = os.environ.get(variable + "_FILE")
        if path and variable not in os.environ:
            secrets[field] = _read_secret_file(path, field)
    return secrets


def _read_secret_file(path: str, field: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").removesuffix("\n")
    except (OSError, UnicodeDecodeError):
        pass
    # Raised outside the except block so the OSError, which names the path, is not chained.
    raise SettingsError(f"invalid or missing settings: {field} (secret file unreadable)")


def load_settings() -> Settings:
    """Build settings from the environment, uncached; raise SettingsError if invalid."""
    try:
        return Settings(**_secrets_from_files())
    except ValidationError as exc:
        fields = sorted({".".join(map(str, error["loc"])) for error in exc.errors()})
    # Raised outside the except block: pydantic's error echoes input values (passwords).
    raise SettingsError("invalid or missing settings: " + ", ".join(fields))


@cache
def get_settings() -> Settings:
    """The process-wide settings, loaded once."""
    return load_settings()
