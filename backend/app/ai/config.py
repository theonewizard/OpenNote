"""AI settings from OPENNOTE_AI_* environment variables. The API key may come from
OPENNOTE_AI_API_KEY_FILE instead, like the other secrets (app.core.config)."""

import ipaddress
from functools import cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import SettingsError, _secrets_from_files

# Host names that only resolve inside a private network: Compose service names (no dot),
# mDNS, and Kubernetes or OpenShift cluster DNS.
_LOCAL_SUFFIXES = (".local", ".internal", ".lan", ".svc", ".svc.cluster.local", ".localhost")


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPENNOTE_AI_", frozen=True)

    provider: Literal["none", "ollama", "openai"] = Field(
        default="none",
        description="none (default, AI off), ollama, or openai: any OpenAI-compatible "
        "endpoint such as a llama.cpp server or an external provider",
    )
    base_url: AnyHttpUrl | None = Field(
        default=None,
        description="Ollama: http://ollama:11434; OpenAI-compatible: the URL up to and "
        "including /v1, such as http://llama:8080/v1",
    )
    embed_model: str | None = Field(default=None, min_length=1, max_length=200)
    chat_model: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: SecretStr | None = Field(default=None, repr=False)
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    # Claude (Anthropic API): an external provider for the vault assistant, never for
    # embeddings (Anthropic has no embeddings API). On when the key is set.
    claude_api_key: SecretStr | None = Field(default=None, repr=False)
    claude_model: str = Field(default="claude-opus-5-5", min_length=1, max_length=200)
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"

    @model_validator(mode="after")
    def _provider_needs_url(self) -> AISettings:
        if self.provider != "none" and self.base_url is None:
            raise ValueError("base_url is required when provider is set")
        return self

    @property
    def external(self) -> bool:
        """True unless base_url points at this machine or a private network: such a
        provider receives note text only from vaults that opted in (allow_external)."""
        return self.base_url is not None and not is_local_host(self.base_url.host or "")


def is_local_host(host: str) -> bool:
    """Loopback, private, link-local or unique-local addresses, single-label names and
    private DNS suffixes count as local; everything else, unknown names included, is
    external."""
    host = host.strip("[]").rstrip(".").lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host == "localhost" or "." not in host or host.endswith(_LOCAL_SUFFIXES)
    return address.is_loopback or address.is_private or address.is_link_local


def load_ai_settings() -> AISettings:
    """Build the AI settings, uncached; raise SettingsError naming fields, never values."""
    files = _secrets_from_files(["ai_api_key", "ai_claude_api_key"])
    secrets = {k.removeprefix("ai_"): v for k, v in files.items() if v}
    try:
        return AISettings(**secrets)
    except ValidationError as exc:
        # The model-level check has no location; it is about base_url.
        fields = sorted(
            {"ai_" + (".".join(map(str, e["loc"])) or "base_url") for e in exc.errors()}
        )
    # Raised outside the except block: pydantic's error echoes input values (the key).
    raise SettingsError("invalid or missing settings: " + ", ".join(fields))


@cache
def get_ai_settings() -> AISettings:
    return load_ai_settings()
