"""A note saved through the API asks the worker to re-embed its vault, only when the
server has an AI provider, and a broker failure never fails the save."""

import pytest
from dramatiq import Message
from dramatiq.brokers.stub import StubBroker

from app.ai import jobs, notify
from app.ai.config import AISettings

pytestmark = pytest.mark.anyio

LOCAL = AISettings(provider="ollama", base_url="http://127.0.0.1:11434", embed_model="m")


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> StubBroker:
    broker = StubBroker()
    broker.declare_queue("default")
    monkeypatch.setattr(notify, "_broker", lambda settings: broker)
    return broker


def sent(broker: StubBroker) -> list[Message]:
    queue = broker.queues["default"]
    return [Message.decode(queue.get_nowait()) for _ in range(queue.qsize())]


async def _create(api, headers, vault):
    body = {"vault_id": str(vault), "path": "Inbox/Idea.md", "content": "hello\n"}
    response = await api.client.post("/api/v1/notes", json=body, headers=headers)
    assert response.status_code == 201, response.text


async def test_a_save_enqueues_the_embedding_job(api, stub, monkeypatch):
    monkeypatch.setattr(notify, "get_ai_settings", lambda: LOCAL)
    alice = api.user("alice")
    vault = api.vault(alice)
    await _create(api, await api.bearer(alice), vault)
    [message] = sent(stub)
    assert (message.actor_name, message.args) == (jobs.embed_vault_job.actor_name, (str(vault),))
    assert message.queue_name == jobs.embed_vault_job.queue_name


async def test_nothing_is_enqueued_while_ai_is_off(api, stub):
    alice = api.user("alice")
    await _create(api, await api.bearer(alice), api.vault(alice))
    assert sent(stub) == []


async def test_a_broken_broker_does_not_fail_the_save(api, monkeypatch, caplog):
    monkeypatch.setattr(notify, "get_ai_settings", lambda: LOCAL)

    def broken(settings):
        raise ConnectionError("valkey down")

    monkeypatch.setattr(notify, "_broker", broken)
    alice = api.user("alice")
    await _create(api, await api.bearer(alice), api.vault(alice))
    assert "embedding not requested" in caplog.text
