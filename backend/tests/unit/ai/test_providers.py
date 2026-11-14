"""The HTTP providers against a stub server on loopback: request shapes, response checks,
errors that name no URL or key, no redirects, and timeouts."""

import json
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from app.ai.config import AISettings
from app.ai.providers import AIError, OllamaProvider, OpenAICompatibleProvider

Reply = tuple[int, Any, dict[str, str]]


class Stub:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str], Any]] = []
        self.reply: Callable[[str, Any], Reply] = lambda path, body: (404, {}, {})
        self.url = ""


@pytest.fixture
def stub() -> Iterator[Stub]:
    state = Stub()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append((self.path, dict(self.headers), body))
            status, payload, headers = state.reply(self.path, body)
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state
    server.shutdown()
    server.server_close()


def ollama(stub: Stub, **kw: Any) -> OllamaProvider:
    return OllamaProvider(AISettings(provider="ollama", base_url=stub.url, **kw))


def openai(stub: Stub, **kw: Any) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(AISettings(provider="openai", base_url=stub.url + "/v1", **kw))


def test_ollama_embed(stub):
    stub.reply = lambda path, body: (200, {"embeddings": [[0.1, 2], [3, 4.5]]}, {})
    assert ollama(stub).embed(["a", "b"], "nomic-embed-text") == [[0.1, 2.0], [3.0, 4.5]]
    [(path, headers, body)] = stub.requests
    assert path == "/api/embed"
    assert body == {"model": "nomic-embed-text", "input": ["a", "b"]}
    assert "Authorization" not in headers


def test_ollama_generate_keeps_system_and_prompt_apart(stub):
    stub.reply = lambda path, body: (200, {"message": {"role": "assistant", "content": "hi"}}, {})
    assert ollama(stub).generate("note text", system="rules", model="llama3") == "hi"
    [(path, _, body)] = stub.requests
    assert path == "/api/chat"
    assert body["messages"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "note text"},
    ]
    assert body["stream"] is False


def test_openai_embed_orders_by_index_and_sends_the_key(stub):
    data = [{"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]}]
    stub.reply = lambda path, body: (200, {"data": data}, {})
    provider = openai(stub, api_key="sk-marker")
    assert provider.embed(["a", "b"], "text-embedding-3-small") == [[1.0], [2.0]]
    [(path, headers, _)] = stub.requests
    assert path == "/v1/embeddings"
    assert headers["Authorization"] == "Bearer sk-marker"


def test_openai_generate(stub):
    reply = {"choices": [{"message": {"role": "assistant", "content": "done"}}]}
    stub.reply = lambda path, body: (200, reply, {})
    assert openai(stub).generate("p", system="s", model="m") == "done"
    assert stub.requests[0][0] == "/v1/chat/completions"


@pytest.mark.parametrize(
    "payload",
    [
        {"embeddings": [[1.0]]},  # one vector for two texts
        {"embeddings": [[1.0], [1.0, 2.0]]},  # dimensions differ
        {"embeddings": [[1.0], []]},
        {"embeddings": [[1.0], ["x"]]},
        {"embeddings": [[1.0], [True]]},
        {"embeddings": "nope"},
        b"[1, NaN]",
        b"not json",
        [],
    ],
)
def test_malformed_embeddings_are_refused(stub, payload):
    stub.reply = lambda path, body: (200, payload, {})
    with pytest.raises(AIError):
        ollama(stub).embed(["a", "b"], "m")


def test_a_nan_inside_an_embedding_is_refused(stub):
    stub.reply = lambda path, body: (200, b'{"embeddings": [[1.0, NaN]]}', {})
    with pytest.raises(AIError, match="malformed"):
        ollama(stub).embed(["a"], "m")


def test_http_errors_name_neither_url_nor_key(stub):
    stub.reply = lambda path, body: (500, {"error": "boom"}, {})
    with pytest.raises(AIError) as info:
        openai(stub, api_key="sk-marker").embed(["a"], "m")
    assert str(info.value) == "openai /embeddings: HTTP 500"


def test_redirects_are_not_followed(stub):
    def reply(path: str, body: Any) -> Reply:
        if path == "/v1/embeddings":
            return 307, {}, {"Location": stub.url + "/elsewhere"}
        return 200, {"data": [{"index": 0, "embedding": [1.0]}]}, {}

    stub.reply = reply
    with pytest.raises(AIError, match="HTTP 307"):
        openai(stub, api_key="sk-marker").embed(["a"], "m")
    assert [r[0] for r in stub.requests] == ["/v1/embeddings"]


def test_an_unreachable_provider_fails_cleanly():
    provider = OllamaProvider(AISettings(provider="ollama", base_url="http://127.0.0.1:9"))
    with pytest.raises(AIError, match="unreachable"):
        provider.embed(["a"], "m")


def test_a_slow_provider_times_out(stub):
    def slow(path: str, body: Any) -> Reply:
        time.sleep(1)
        return 200, {"embeddings": [[1.0]]}, {}

    stub.reply = slow
    with pytest.raises(AIError, match="unreachable"):
        ollama(stub, timeout_seconds=0.2).embed(["a"], "m")
