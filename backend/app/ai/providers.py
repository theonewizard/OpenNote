"""The provider interface (ADR-0016) and its HTTP implementations: Ollama, and any
OpenAI-compatible endpoint (llama.cpp server, vLLM, or an opted-in external provider).

Synchronous on purpose: providers are called from worker jobs, not from request handlers.
Transcription (faster-whisper) joins the interface with P7-07.
"""

import json
import logging
import math
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any, Protocol

from app.ai.config import AISettings

log = logging.getLogger(__name__)

# A batch of 32 embeddings of 4096 dimensions is about 3 MiB of JSON.
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class AIError(Exception):
    """A provider call failed. The message is safe to log: no URL, key or note text."""


class AIProvider(Protocol):
    name: str
    external: bool

    def embed(self, texts: Sequence[str], model: str) -> list[list[float]]:
        """One vector per text, in order, all of the same dimension."""
        ...

    def generate(self, prompt: str, *, system: str, model: str) -> str:
        """One completion of `prompt` under the fixed `system` instructions."""
        ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the Authorization header to wherever it points."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


class _HTTPProvider:
    name = "http"

    def __init__(self, settings: AISettings) -> None:
        if settings.base_url is None:  # AISettings refuses a provider without one
            raise AIError(f"{self.name}: no base_url")
        self._base = str(settings.base_url).rstrip("/")
        self._timeout = settings.timeout_seconds
        self._key = settings.api_key
        self.external = settings.external

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._key is not None:
            headers["Authorization"] = "Bearer " + self._key.get_secret_value()
        request = urllib.request.Request(  # noqa: S310 - AnyHttpUrl allows http(s) only
            self._base + path, data=json.dumps(payload).encode(), headers=headers
        )
        try:
            with _opener.open(request, timeout=self._timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            exc.close()  # it holds the response body open
            raise AIError(f"{self.name} {path}: HTTP {exc.code}") from None
        except (OSError, ValueError) as exc:  # URLError, timeouts, refused connections
            log.warning("%s %s: %s", self.name, path, type(exc).__name__)
            raise AIError(f"{self.name} {path}: provider unreachable") from None
        if len(body) > MAX_RESPONSE_BYTES:
            raise AIError(f"{self.name} {path}: response too large")
        try:
            return json.loads(body)
        except ValueError:
            raise AIError(f"{self.name} {path}: response is not JSON") from None


def _vectors(value: Any, count: int, name: str) -> list[list[float]]:
    """Check what the provider sent: `count` non-empty lists of finite numbers of one size."""
    if not isinstance(value, list) or len(value) != count:
        raise AIError(f"{name}: expected {count} embeddings")
    vectors: list[list[float]] = []
    for vector in value:
        if not isinstance(vector, list) or not vector:
            raise AIError(f"{name}: malformed embedding")
        floats = [
            float(x) for x in vector if isinstance(x, int | float) and not isinstance(x, bool)
        ]
        if len(floats) != len(vector) or not all(map(math.isfinite, floats)):
            raise AIError(f"{name}: malformed embedding")
        vectors.append(floats)
    if len({len(v) for v in vectors}) > 1:
        raise AIError(f"{name}: embeddings differ in dimension")
    return vectors


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise AIError(f"{name}: malformed completion")
    return value


class OllamaProvider(_HTTPProvider):
    name = "ollama"

    def embed(self, texts: Sequence[str], model: str) -> list[list[float]]:
        data = self._post("/api/embed", {"model": model, "input": list(texts)})
        return _vectors(isinstance(data, dict) and data.get("embeddings"), len(texts), self.name)

    def generate(self, prompt: str, *, system: str, model: str) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        data = self._post("/api/chat", {"model": model, "messages": messages, "stream": False})
        try:
            return _text(data["message"]["content"], self.name)
        except KeyError, TypeError:
            raise AIError(f"{self.name}: malformed completion") from None


class OpenAICompatibleProvider(_HTTPProvider):
    name = "openai"

    def embed(self, texts: Sequence[str], model: str) -> list[list[float]]:
        data = self._post("/embeddings", {"model": model, "input": list(texts)})
        try:
            items = sorted(data["data"], key=lambda item: item["index"])
            value = [item["embedding"] for item in items]
        except KeyError, TypeError:
            raise AIError(f"{self.name}: malformed embeddings") from None
        return _vectors(value, len(texts), self.name)

    def generate(self, prompt: str, *, system: str, model: str) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        data = self._post("/chat/completions", {"model": model, "messages": messages})
        try:
            return _text(data["choices"][0]["message"]["content"], self.name)
        except KeyError, IndexError, TypeError:
            raise AIError(f"{self.name}: malformed completion") from None


def provider_from_settings(settings: AISettings) -> AIProvider | None:
    """The configured provider, or None when AI is off (the default)."""
    match settings.provider:
        case "ollama":
            return OllamaProvider(settings)
        case "openai":
            return OpenAICompatibleProvider(settings)
        case _:
            return None
