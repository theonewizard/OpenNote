"""P8-01: the server's design §15.14 targets on a real vault of Markdown files on disk.

Slow: skipped unless selected with `-m slow`. Unlike test_search_perf.py, nothing is
written into the tables directly: the notes are files in a vault folder and reach the
database the way an existing Obsidian vault does, through the vault watcher's first full
scan (`python -m app.vaults`). Then the API is timed in process (ASGI, no network):

- import: first full scan and commit of every note (no target; recorded)
- rebuild: `rebuild_index` of the whole vault from disk (no target; recorded)
- open: GET /notes/{id}/content, target p95 < 200 ms (cached open)
- save: PUT /notes/{id}/content, a full commit through the sync path (recorded)
- list, links, tags: first page of a folder, a note's links, the tag counts (recorded)
- search: target p95 < 500 ms

`OPENNOTE_TEST_BENCH_NOTES` sets the note count (default 100,000), `OPENNOTE_TEST_BENCH_OUT` a
path the results are written to as JSON. docs/development/benchmarks.md records them.
"""

import json
import math
import os
import platform
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import anyio
import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Committers
from app.notes.index import rebuild_index
from app.notes.models import File, Note
from app.vaults import __main__ as service
from app.vaults.models import Vault
from app.vaults.watch import VaultWatcher

pytestmark = [pytest.mark.slow, pytest.mark.anyio]

NOTES = int(os.environ.get("OPENNOTE_TEST_BENCH_NOTES", "100000"))
FOLDERS = max(1, NOTES // 1000)
SAMPLES = 200
WORDS = [
    *("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "meeting", "budget"),
    *("quantum", "report", "plan", "review", "draft", "idea", "project", "customer"),
    *("invoice", "travel", "garden", "recipe", "kernel", "cluster", "storage", "network"),
    *("backup", "restore", "release", "roadmap", "design", "spec", "decision", "risk"),
]
SEARCHES = [
    "alpha",
    "quantum report",
    "meeting OR budget",
    '"alpha bravo"',
    "tag:tag7",
    "tag:project",
    "path:Folder12",
    "has:task",
    "-alpha bravo",
    "title:kernel",
    "(alpha OR bravo) -charlie tag:tag12",
    "nothingmatchesthis",
]


@pytest.fixture(autouse=True)
def _only_when_selected(request: pytest.FixtureRequest) -> None:
    if "slow" not in (request.config.getoption("markexpr") or ""):
        pytest.skip("slow: run with -m slow")


def _note(i: int, rng: random.Random) -> str:
    """A note of about 1.5 KB: frontmatter tags, a heading, paragraphs, two wikilinks to
    other notes and, in every tenth note, a task."""
    words = lambda n: " ".join(rng.choice(WORDS) for _ in range(n))  # noqa: E731
    links = " ".join(f"[[Note {rng.randrange(NOTES)}]]" for _ in range(2))
    task = "\n- [ ] follow up with the owner\n" if i % 10 == 0 else ""
    return (
        f"---\ntags: [tag{i % 200}, project/p{i % 20}]\n---\n"
        f"# {words(3).title()} {i}\n\n"
        + "\n\n".join(words(40) for _ in range(5))
        + f"\n\nSee {links}.\n{task}"
    )


def _write_vault(root: Path) -> None:
    rng = random.Random(8)
    for f in range(FOLDERS):
        (root / f"Folder{f}").mkdir()
    for i in range(NOTES):
        (root / f"Folder{i % FOLDERS}" / f"Note {i}.md").write_text(_note(i, rng))


def _stats(timings: list[float]) -> dict[str, float]:
    timings = sorted(timings)
    pick = lambda q: timings[math.ceil(q * len(timings)) - 1] * 1000  # noqa: E731
    return {"n": len(timings), "p50_ms": pick(0.5), "p95_ms": pick(0.95), "max_ms": pick(1.0)}


async def _time(
    call: Callable[[int], Awaitable[httpx2.Response]], n: int, ok: int = 200
) -> dict[str, float]:
    timings = []
    for i in range(n):
        start = time.perf_counter()
        response = await call(i)
        timings.append(time.perf_counter() - start)
        assert response.status_code == ok, response.text
    return _stats(timings)


async def test_vault_targets_on_100k_notes(api):
    alice = api.user("alice")
    vault_id = api.vault(alice, "Big")
    headers = await api.bearer(alice)
    with Session(api.engine) as s:
        root = Path(s.get(Vault, vault_id).root_path)
    results: dict[str, object] = {
        "notes": NOTES,
        "python": platform.python_version(),
        "cpus": os.cpu_count(),
        "machine": platform.machine(),
    }

    start = time.perf_counter()
    await anyio.to_thread.run_sync(_write_vault, root)
    results["write_files_s"] = round(time.perf_counter() - start, 1)

    committers = Committers(api.settings)
    watchers: dict[uuid.UUID, VaultWatcher] = {}
    try:
        start = time.perf_counter()
        await anyio.to_thread.run_sync(service.sync_watchers, committers, watchers)
        results["import_s"] = round(time.perf_counter() - start, 1)
    finally:
        for watcher in watchers.values():
            watcher.stop()
        committers.close()

    with Session(api.engine) as s:
        assert s.scalar(select(func.count()).select_from(Note)) == NOTES
    start = time.perf_counter()
    with Session(api.engine) as s, s.begin():
        rebuild_index(s, vault_id, root)
    results["rebuild_s"] = round(time.perf_counter() - start, 1)

    rng = random.Random(9)
    sample = rng.sample(range(NOTES), SAMPLES)
    with Session(api.engine) as s:
        ids = [
            str(file_id)
            for (file_id,) in s.execute(
                select(File.file_id).where(
                    File.path.in_([f"Folder{i % FOLDERS}/Note {i}.md" for i in sample])
                )
            )
        ]
    assert len(ids) == SAMPLES

    def notes(suffix: str = "") -> Callable[[int], str]:
        return lambda i: f"/api/v1/notes/{ids[i % len(ids)]}{suffix}"

    content = notes("/content")
    results["open"] = await _time(lambda i: api.client.get(content(i), headers=headers), SAMPLES)

    async def save(i: int) -> httpx2.Response:
        url = content(i)
        current = await api.client.get(url, headers=headers)
        body = current.content + b"\nedited by the benchmark\n"
        start = time.perf_counter()
        response = await api.client.put(
            url,
            content=body,
            headers={
                **headers,
                "If-Match": current.headers["ETag"],
                "Content-Type": "text/markdown",
            },
        )
        save_timings.append(time.perf_counter() - start)
        return response

    save_timings: list[float] = []
    await _time(save, 50)
    results["save"] = _stats(save_timings)

    results["list"] = await _time(
        lambda i: api.client.get(
            "/api/v1/notes",
            params={"vault_id": str(vault_id), "folder": f"Folder{i % FOLDERS}"},
            headers=headers,
        ),
        50,
    )
    links = notes("/links")
    results["links"] = await _time(lambda i: api.client.get(links(i), headers=headers), SAMPLES)
    results["tags"] = await _time(
        lambda i: api.client.get(
            "/api/v1/tags", params={"vault_id": str(vault_id)}, headers=headers
        ),
        10,
    )
    results["search"] = await _time(
        lambda i: api.client.get(
            "/api/v1/search", params={"q": SEARCHES[i % len(SEARCHES)]}, headers=headers
        ),
        len(SEARCHES) * 3,
    )

    report = json.dumps(results, indent=2)
    print(report)
    if out := os.environ.get("OPENNOTE_TEST_BENCH_OUT"):
        await anyio.Path(out).write_text(report + "\n")
    assert results["open"]["p95_ms"] < 200  # type: ignore[index]
    assert results["search"]["p95_ms"] < 500  # type: ignore[index]
