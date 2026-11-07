"""Search latency on a generated 100k-note vault (P2-08 target: p95 < 500 ms).

Slow: skipped unless selected with `-m slow`. The notes are written straight into the
tables (files, notes, note_tags, search_documents, revisions), not through the Committer.
"""

import math
import random
import time

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

pytestmark = [pytest.mark.slow, pytest.mark.anyio]

NOTES = 100_000
VOCABULARY = 5_000
QUERIES = [
    "alpha",
    "zebra",
    "lorem",
    "kab",
    "quantum report",
    "meeting OR budget",
    '"alpha bravo"',
    "chitect",
    "tag:tag7",
    "tag:project",
    "notebook:Folder3",
    "path:Folder12",
    "created:2026-03-01..2026-03-31",
    "after:2026-06-01 alpha",
    "has:task",
    "is:favorite",
    "-alpha bravo",
    "title:delta",
    "(alpha OR bravo) -charlie tag:tag12",
    "nothingmatchesthis",
]


@pytest.fixture(autouse=True)
def _only_when_selected(request: pytest.FixtureRequest) -> None:
    if "slow" not in (request.config.getoption("markexpr") or ""):
        pytest.skip("slow: run with -m slow")


def _words() -> list[str]:
    rng = random.Random(7)
    common = ["alpha", "bravo", "charlie", "delta", "meeting", "budget", "quantum", "report"]
    letters = "abcdefghijklmnopqrstuvwxyz"
    made = {"".join(rng.choice(letters) for _ in range(rng.randint(3, 10))) for _ in range(9000)}
    return common + sorted(made - set(common))[: VOCABULARY - len(common)]


GENERATE = """
CREATE TEMP TABLE gen AS
SELECT i, gen_random_uuid() AS file_id,
       'Folder' || (i % 50) || '/Note ' || i || '.md' AS path,
       (SELECT string_agg(v.w, ' ' ORDER BY k) FROM generate_series(1, 3) k
          JOIN vocab v ON v.id = (i * 13 + k * 7919 + (i * k) % 911) % :n) AS title,
       (SELECT string_agg(v.w, ' ' ORDER BY k) FROM generate_series(1, 60) k
          JOIN vocab v ON v.id = ((i * 31 + k * 104729 + (i * k) % 997) % :n)) AS body
FROM generate_series(1, :notes) i;
INSERT INTO files (file_id, vault_id, path, path_key, kind, size, content_hash, revision)
  SELECT file_id, :vault, path, lower(path), 'note', length(body), 'sha256-x', 1 FROM gen;
INSERT INTO notes (file_id, title, properties, frontmatter_error, read_only)
  SELECT file_id, title,
         CASE WHEN i % 100 = 0 THEN '{"opennote": {"favorite": true}}'::jsonb END, false, false
  FROM gen;
INSERT INTO note_tags (file_id, tag_key, tag)
  SELECT file_id, 'tag' || (i % 200), 'tag' || (i % 200) FROM gen
  UNION ALL SELECT file_id, 'project/p' || (i % 20), 'project/p' || (i % 20) FROM gen;
INSERT INTO search_documents (file_id, vault_id, title, keywords, body)
  SELECT file_id, :vault, title, 'tag' || (i % 200) || ' project/p' || (i % 20),
         body || CASE WHEN i % 2 = 0 THEN ' alpha' ELSE '' END
              || CASE WHEN i % 10 = 0 THEN E'\n- [ ] follow up' ELSE '' END
  FROM gen;
INSERT INTO revisions (vault_id, seq, file_id, revision, path, kind, content_hash, size,
                       deleted, device_id, op, committed_at)
  SELECT :vault, i, file_id, 1, path, 'note', 'sha256-x', length(body), false, 'gen', 'create',
         timestamptz '2026-01-01 12:00Z' + make_interval(days => i % 300)
  FROM gen;
"""


async def test_search_p95_on_100k_notes(api):
    alice = api.user("alice")
    vault = api.vault(alice, "Big")
    api.vault(alice, "Small")  # a second vault in scope
    with Session(api.engine) as s, s.begin():
        s.execute(text("CREATE TEMP TABLE vocab (id int PRIMARY KEY, w text)"))
        s.execute(
            text("INSERT INTO vocab VALUES (:id, :w)"),
            [{"id": i, "w": w} for i, w in enumerate(_words())],
        )
        for statement in GENERATE.split(";\n"):
            if statement.strip():
                s.execute(text(statement), {"n": VOCABULARY, "notes": NOTES, "vault": vault})
    with api.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("VACUUM ANALYZE"))

    headers = await api.bearer(alice)
    await api.client.get("/api/v1/search", params={"q": "warmup"}, headers=headers)
    timings, hits = [], {}
    for q in QUERIES:
        start = time.perf_counter()
        response = await api.client.get("/api/v1/search", params={"q": q}, headers=headers)
        timings.append(time.perf_counter() - start)
        assert response.status_code == 200, response.text
        hits[q] = len(response.json()["items"])
    timings.sort()
    p95 = timings[math.ceil(0.95 * len(timings)) - 1]
    print(f"search p95 over {len(QUERIES)} queries on {NOTES} notes: {p95 * 1000:.0f} ms")
    print("hits per query (page of 50):", hits)
    assert hits["alpha"] == 50 and hits["tag:tag7"] == 50 and hits["nothingmatchesthis"] == 0
    print("slowest:", [f"{t * 1000:.0f}" for t in timings[-5:]])
    assert p95 < 0.5
