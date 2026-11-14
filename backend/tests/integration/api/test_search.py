"""Tags (P2-07) and search (P2-08) over notes committed through the Committer."""

import datetime as dt
import hashlib
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.auth.models import User
from app.sync.commit import Create, Delete, Update
from app.sync.models import Conflict
from app.vaults.models import Vault
from app.vaults.paths import classify
from tests.compatibility.corpus import corpus_cases

pytestmark = pytest.mark.anyio

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def committer(api, vault_id: uuid.UUID):
    with Session(api.engine) as s:
        root = s.get(Vault, vault_id).root_path
    return api.app.state.committers.get(vault_id, root)


def put(api, vault_id: uuid.UUID, path: str, data: bytes | str, *, on: str = "2026-01-01"):
    """Commit a new file on day `on` and return its id."""
    blob = data.encode() if isinstance(data, str) else data
    c = committer(api, vault_id)
    c.clock = lambda: dt.datetime.fromisoformat(on + "T12:00:00+00:00")
    file_id = uuid.uuid7()
    result = c.commit(Create(uuid.uuid7(), file_id, path, classify(path), _sha(blob)), "dev", blob)
    assert result.status == "applied", result
    return file_id


def edit(api, vault_id: uuid.UUID, file_id: uuid.UUID, revision: int, data: str, *, on: str):
    blob = data.encode()
    c = committer(api, vault_id)
    c.clock = lambda: dt.datetime.fromisoformat(on + "T12:00:00+00:00")
    assert c.commit(Update(uuid.uuid7(), file_id, revision, _sha(blob)), "dev", blob).status in (
        "applied",
        "merged",
    )


@dataclass
class Fixture:
    alice: User
    headers: dict[str, str]
    work: uuid.UUID
    ids: dict[str, uuid.UUID]


ARCH = """---
tags: [project/alpha, Architecture]
aliases: [Arch Design]
opennote:
  favorite: true
---
The system architecture uses PostgreSQL.

- [ ] write the spec

![[diagram.png]] and [[Missing note]]
"""


@pytest.fixture
async def fx(api) -> Fixture:
    alice = api.user("alice")
    work = api.vault(alice, "Work")
    ids = {
        "png": put(api, work, "Work/diagram.png", PNG),
        "pdf": put(api, work, "Work/report.pdf", b"%PDF-1.4 fake"),
        "arch": put(api, work, "Work/Projects/Architecture.md", ARCH, on="2026-01-10"),
        "sync": put(
            api,
            work,
            "Work/Weekly Sync.md",
            "Notes from the weekly sync meeting. #meeting\n\nSee [[report.pdf]].\n",
            on="2026-02-15",
        ),
        "recipes": put(
            api,
            work,
            "Personal/Recipes.md",
            "---\nopennote: {archived: true}\n---\nPancakes need flour and eggs. #cooking\n",
            on="2026-03-05",
        ),
        "draft": put(
            api,
            work,
            "Personal/Old draft.md",
            "A draft text about architecture. #project\n",
            on="2026-04-01",
        ),
    }
    edit(
        api,
        work,
        ids["sync"],
        1,
        "Notes from the weekly sync meeting. #meeting\n\nSee [[report.pdf]].\nMore.\n",
        on="2026-03-01",
    )
    with Session(api.engine) as s, s.begin():
        s.add(
            Conflict(
                id=uuid.uuid7(),
                vault_id=work,
                file_id=ids["arch"],
                copy_file_id=ids["draft"],
                base_revision=1,
                their_revision=1,
            )
        )
    return Fixture(alice, await api.bearer(alice), work, ids)


async def found(api, fx: Fixture, q: str, **params) -> list[str]:
    response = await api.client.get(
        "/api/v1/search", params={"q": q, "vault_id": str(fx.work), **params}, headers=fx.headers
    )
    assert response.status_code == 200, response.text
    names = {v: k for k, v in fx.ids.items()}
    return [names[uuid.UUID(hit["note"]["id"])] for hit in response.json()["items"]]


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("architecture", ["arch", "draft"]),  # title match ranks first
        ("archi", ["arch", "draft"]),  # prefix
        ("chitect", ["arch", "draft"]),  # partial word, trigram substring
        ("postgresql spec", ["arch"]),  # implicit AND
        ("Arch Design", ["arch"]),  # aliases
        ("pancakes OR meeting", None),
        ('"weekly sync meeting"', ["sync"]),
        ('"meeting weekly"', []),
        ("architecture -draft", ["arch"]),
        ("-tag:project", None),
        ("(pancakes OR eggs) -tag:cooking", []),
        ("tag:project", None),
        ("tag:PROJECT/alpha", ["arch"]),
        ("tag:alpha", []),
        ("tag:#meeting", ["sync"]),
        ("notebook:work", None),
        ("path:Work/Projects", ["arch"]),
        ("path:Work/Proj", []),
        ('title:"weekly sync"', ["sync"]),
        ("title:arch", ["arch"]),
        ("type:image", ["arch"]),
        ("type:pdf", ["sync"]),
        ("type:audio", []),
        ("has:attachment", None),
        ("has:link", None),
        ("has:unresolved", ["arch"]),
        ("has:task", ["arch"]),
        ("created:2026-01-10", ["arch"]),
        ("created:2026-02-01..2026-03-31", None),
        ("modified:2026-03-01", ["sync"]),
        ("modified:2026-02-15", []),
        ("before:2026-02-01", ["arch"]),
        ("after:2026-03-01", None),
        ("is:favorite", ["arch"]),
        ("is:archived", ["recipes"]),
        ("is:conflict", ["draft"]),
        ("-is:favorite -is:archived -is:conflict", ["sync"]),
        ("color:red", []),
        ("()", []),
    ],
)
async def test_filters_and_operators(api, fx, q, expected):
    sets = {
        "pancakes OR meeting": {"recipes", "sync"},
        "-tag:project": {"sync", "recipes"},
        "tag:project": {"arch", "draft"},
        "notebook:work": {"arch", "sync"},
        "has:attachment": {"arch", "sync"},
        "has:link": {"arch", "sync"},
        "created:2026-02-01..2026-03-31": {"sync", "recipes"},
        "after:2026-03-01": {"recipes", "draft"},
    }
    hits = await found(api, fx, q)
    if expected is None:
        assert set(hits) == sets[q] and len(hits) == len(sets[q])
    else:
        assert hits == expected


async def test_hit_carries_note_metadata_and_snippet(api, fx):
    response = await api.client.get(
        "/api/v1/search", params={"q": "postgresql"}, headers=fx.headers
    )
    [hit] = response.json()["items"]
    note = hit["note"]
    assert note["path"] == "Work/Projects/Architecture.md"
    assert note["title"] == "Architecture"
    assert sorted(note["tags"]) == ["Architecture", "project/alpha"]
    assert note["aliases"] == ["Arch Design"]
    assert note["properties"]["opennote"] == {"favorite": True}
    assert note["created_at"].startswith("2026-01-10")
    assert note["modified_by_device"] == "dev"
    assert note["revision"] == 1
    assert "«PostgreSQL»" in hit["snippet"]
    assert "favorite" not in hit["snippet"]  # frontmatter is not searched
    assert hit["score"] > 0


async def test_deleted_notes_are_not_found(api, fx):
    c = committer(api, fx.work)
    assert c.commit(Delete(uuid.uuid7(), fx.ids["recipes"], 1), "dev", None).status == "applied"
    assert await found(api, fx, "pancakes") == []


async def test_cursor_pages_through_every_hit_once(api, fx):
    everything = await found(api, fx, "-nothingmatchesthis", limit=500)
    assert len(everything) == 4
    seen, cursor = [], None
    while True:
        params = {"q": "-nothingmatchesthis", "vault_id": str(fx.work), "limit": 1}
        response = await api.client.get(
            "/api/v1/search",
            params=params | ({"cursor": cursor} if cursor else {}),
            headers=fx.headers,
        )
        body = response.json()
        seen += [item["note"]["id"] for item in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    names = {str(v): k for k, v in fx.ids.items()}
    assert [names[i] for i in seen] == everything


async def test_ranked_cursor_continues_after_the_last_score(api, fx):
    first = (
        await api.client.get(
            "/api/v1/search", params={"q": "architecture", "limit": 1}, headers=fx.headers
        )
    ).json()
    second = (
        await api.client.get(
            "/api/v1/search",
            params={"q": "architecture", "limit": 1, "cursor": first["next_cursor"]},
            headers=fx.headers,
        )
    ).json()
    assert first["items"][0]["note"]["path"] == "Work/Projects/Architecture.md"
    assert second["items"][0]["note"]["path"] == "Personal/Old draft.md"
    assert second["next_cursor"] is None


@pytest.mark.parametrize("cursor", ["garbage", "WyJ4IiwieSJd", "WzEsMl0"])
async def test_bad_cursor_is_400(api, fx, cursor):
    response = await api.client.get(
        "/api/v1/search", params={"q": "x", "cursor": cursor}, headers=fx.headers
    )
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"


async def test_search_is_scoped(api, fx):
    bob = api.user("bob")
    secret = api.vault(bob, "Secret")
    put(api, secret, "Secret architecture.md", "architecture of the secret project\n")
    shared = api.vault(bob, "Shared", alice="viewer")
    put(api, shared, "Shared architecture.md", "shared architecture\n")
    gone = api.vault(fx.alice, "Gone")
    put(api, gone, "Gone architecture.md", "gone architecture\n")
    with Session(api.engine) as s, s.begin():
        s.execute(update(Vault).where(Vault.id == gone).values(deleted_at=dt.datetime.now(dt.UTC)))

    response = await api.client.get(
        "/api/v1/search", params={"q": "architecture", "limit": 500}, headers=fx.headers
    )
    paths = {hit["note"]["path"] for hit in response.json()["items"]}
    assert paths == {
        "Work/Projects/Architecture.md",
        "Personal/Old draft.md",
        "Shared architecture.md",
    }
    for vault in (secret, gone, uuid.uuid7()):
        response = await api.client.get(
            "/api/v1/search",
            params={"q": "architecture", "vault_id": str(vault)},
            headers=fx.headers,
        )
        assert response.status_code == 404
    bob_hits = await api.client.get(
        "/api/v1/search", params={"q": "architecture"}, headers=await api.bearer(bob)
    )
    assert {h["note"]["path"] for h in bob_hits.json()["items"]} == {
        "Secret architecture.md",
        "Shared architecture.md",
    }


async def test_pat_reaches_only_its_vaults(api, fx):
    other = api.vault(fx.alice, "Other")
    put(api, other, "Other architecture.md", "architecture elsewhere\n")
    key = api.api_key(fx.alice, [fx.work])
    response = await api.client.get("/api/v1/search", params={"q": "architecture"}, headers=key)
    assert {h["note"]["path"] for h in response.json()["items"]} == {
        "Work/Projects/Architecture.md",
        "Personal/Old draft.md",
    }
    response = await api.client.get(
        "/api/v1/search", params={"q": "architecture", "vault_id": str(other)}, headers=key
    )
    assert response.status_code == 404
    response = await api.client.get("/api/v1/tags", params={"vault_id": str(other)}, headers=key)
    assert response.status_code == 404


async def test_search_needs_credentials(api):
    assert (await api.client.get("/api/v1/search", params={"q": "x"})).status_code == 401
    assert (
        await api.client.get("/api/v1/tags", params={"vault_id": str(uuid.uuid7())})
    ).status_code == 401


# Tags -------------------------------------------------------------------------------------


async def test_tags_with_counts_and_most_common_spelling(api, fx):
    put(api, fx.work, "m1.md", "#Meeting\n")
    put(api, fx.work, "m2.md", "#meeting #B\n")
    put(api, fx.work, "m3.md", "#b #Project\n")
    response = await api.client.get(
        "/api/v1/tags", params={"vault_id": str(fx.work)}, headers=fx.headers
    )
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"name": "Architecture", "count": 1},
            {"name": "B", "count": 2},  # a tie: the smallest spelling
            {"name": "cooking", "count": 1},
            {"name": "meeting", "count": 3},
            {"name": "Project", "count": 2},  # a tie again: "P" sorts before "p"
            {"name": "project/alpha", "count": 1},
        ],
        "next_cursor": None,
    }


async def test_tags_page_by_cursor_and_skip_deleted_notes(api, fx):
    c = committer(api, fx.work)
    assert c.commit(Delete(uuid.uuid7(), fx.ids["recipes"], 1), "dev", None).status == "applied"
    names, cursor = [], None
    while True:
        params = {"vault_id": str(fx.work), "limit": 2} | ({"cursor": cursor} if cursor else {})
        body = (await api.client.get("/api/v1/tags", params=params, headers=fx.headers)).json()
        assert len(body["items"]) <= 2
        names += [t["name"] for t in body["items"]]
        if (cursor := body["next_cursor"]) is None:
            break
    assert names == ["Architecture", "meeting", "project", "project/alpha"]


async def test_tags_of_an_unreachable_vault_are_404(api, fx):
    bob = api.user("bob")
    secret = api.vault(bob, "Secret")
    response = await api.client.get(
        "/api/v1/tags", params={"vault_id": str(secret)}, headers=fx.headers
    )
    assert response.status_code == 404


def _expected_tags(notes: list[list[str]]) -> list[dict[str, object]]:
    """Tag counts computed from the tags of each note, independently of the index."""
    spellings: dict[str, Counter[str]] = {}
    for tags in notes:
        mine: dict[str, str] = {}
        for tag in (t.strip().lstrip("#") for t in tags):
            mine.setdefault(unicodedata.normalize("NFC", tag).casefold(), tag)
        for key, tag in mine.items():
            spellings.setdefault(key, Counter())[tag] += 1
    return [
        {
            "name": min(c, key=lambda t: (-c[t], t)),
            "count": sum(c.values()),
        }
        for _, c in sorted(spellings.items())
    ]


async def test_tag_counts_match_the_corpus(api):
    """Corpus notes (twice each) committed into a vault: GET /tags agrees with counts
    computed from their expected.json. Cases whose body tags expected.json does not list
    are used only when the note has no `#` at all."""
    alice = api.user("alice")
    vault = api.vault(alice, "Corpus")
    notes: list[list[str]] = []
    for case in corpus_cases():
        expected, data = case.expected, case.note_bytes()
        if "tags" not in expected and b"#" in data:
            continue
        frontmatter = expected.get("frontmatter")
        fm_tags = frontmatter.get("tags") if isinstance(frontmatter, dict) else None
        tags = [t for t in fm_tags or [] if isinstance(t, str)] + expected.get("tags", [])
        for folder in ("", "copy/"):
            put(api, vault, f"{folder}{case.name}.md", data)
            notes.append(tags)
    put(api, vault, "Extra.md", "#Work #Tag #Work\n")
    notes.append(["Work", "Tag", "Work"])
    assert sum(1 for tags in notes if tags) > 10  # the corpus does hold tags

    items, cursor = [], None
    while True:
        params = {"vault_id": str(vault), "limit": 3} | ({"cursor": cursor} if cursor else {})
        response = await api.client.get(
            "/api/v1/tags", params=params, headers=await api.bearer(alice)
        )
        items += response.json()["items"]
        if (cursor := response.json()["next_cursor"]) is None:
            break
    assert items == _expected_tags(notes)
