"""`python -m app.vaults`: notes already in a registered folder, and edits made outside
OpenNote, reach the API."""

import asyncio
import datetime as dt
import threading
import uuid
from pathlib import Path

import anyio
import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.api.deps import Committers
from app.vaults import __main__ as service
from app.vaults.models import Vault
from app.vaults.watch import VaultWatcher

pytestmark = pytest.mark.anyio


def _root(api, vault_id: uuid.UUID) -> Path:
    with Session(api.engine) as s:
        return Path(s.get(Vault, vault_id).root_path)


async def _paths(api, headers, vault_id) -> list[str]:
    response = await api.client.get(f"/api/v1/notes?vault_id={vault_id}", headers=headers)
    assert response.status_code == 200, response.text
    return sorted(n["path"] for n in response.json()["items"])


async def test_existing_and_external_notes_are_indexed(api):
    alice = api.user("alice")
    vault_id = api.vault(alice)
    headers = await api.bearer(alice)
    root = _root(api, vault_id)
    (root / "Projects").mkdir()
    (root / "Projects/Plan.md").write_text("# Plan\n")
    (root / "Inbox.md").write_text("first\n")
    assert await _paths(api, headers, vault_id) == []

    committers = Committers(api.settings)
    watchers: dict[uuid.UUID, VaultWatcher] = {}
    try:
        await anyio.to_thread.run_sync(service.sync_watchers, committers, watchers)
        assert set(watchers) == {vault_id}
        assert await _paths(api, headers, vault_id) == ["Inbox.md", "Projects/Plan.md"]

        (root / "Later.md").write_text("made by a script\n")
        for _ in range(60):  # debounce 0.5 s, then the commit
            if "Later.md" in await _paths(api, headers, vault_id):
                break
            await asyncio.sleep(0.1)
        assert await _paths(api, headers, vault_id) == [
            "Inbox.md",
            "Later.md",
            "Projects/Plan.md",
        ]

        with Session(api.engine) as s, s.begin():
            s.execute(
                update(Vault).where(Vault.id == vault_id).values(deleted_at=dt.datetime.now(dt.UTC))
            )
        await anyio.to_thread.run_sync(service.sync_watchers, committers, watchers)
        assert watchers == {}
    finally:
        for watcher in watchers.values():
            watcher.stop()
        committers.close()


async def test_a_second_instance_waits_for_the_first(api, monkeypatch):
    monkeypatch.setattr(service, "POLL_S", 0.05)
    first, second = Committers(api.settings), Committers(api.settings)
    stop_first, stop_second = threading.Event(), threading.Event()
    calls: list[Committers] = []
    monkeypatch.setattr(service, "sync_watchers", lambda c, w: calls.append(c))
    a = threading.Thread(target=service.run, args=(first, stop_first))
    b = threading.Thread(target=service.run, args=(second, stop_second))
    try:
        a.start()
        while not calls:
            stop_first.wait(0.01)
        b.start()
        stop_second.wait(0.3)
        assert second not in calls  # the lock is taken
        stop_first.set()
        a.join(5)
        for _ in range(100):
            if second in calls:
                break
            stop_second.wait(0.05)
        assert second in calls  # took over once the first stopped
    finally:
        stop_first.set()
        stop_second.set()
        a.join(5)
        b.join(5)
        first.close()
        second.close()
