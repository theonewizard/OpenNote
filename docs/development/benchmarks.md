# Benchmarks

Design §15.14 performance targets, measured rather than assumed (P8-01). Reference hardware is in [testing-strategy.md §6](testing-strategy.md#6-reference-hardware-for-performance-targets).

## How they run

`make benchmark` runs both slow benchmarks against the integration-test PostgreSQL and Valkey; `NOTES=N` changes the vault size (default 100,000), `OUT=file.json` writes the vault benchmark's results as JSON. The `benchmark-nightly` job of the backend workflow runs it every night on `main` and on a manual run, with the results in the job summary and the `benchmark-results` artifact.

- `backend/tests/integration/api/test_search_perf.py`: 100,000 notes written straight into the tables; 20 queries of the search grammar; asserts p95 < 500 ms.
- `backend/tests/integration/api/test_vault_perf.py`: 100,000 Markdown files (~1.5 KB each: frontmatter tags, a heading, five paragraphs, two wikilinks to random notes, a task in every tenth) in 100 folders, imported by the vault watcher's first full scan as an existing Obsidian vault would be, then timed through the API in process (ASGI, no network, one client at a time):

| Measure | What | Target |
|---|---|---|
| `import_s` | first full scan and commit of every file | recorded |
| `rebuild_s` | `rebuild_index` of the whole vault from disk | recorded |
| `open` | `GET /notes/{id}/content`, 200 notes | p95 < 200 ms (cached open) |
| `save` | `PUT /notes/{id}/content`, a commit on the sync path, 50 notes | recorded (the < 100 ms local save target is the clients', not the server's) |
| `list` | `GET /notes?folder=` first page, 50 folders | recorded |
| `links` | `GET /notes/{id}/links`, 200 notes | recorded |
| `tags` | `GET /tags` of the vault, 10 calls | recorded |
| `search` | `GET /search`, 12 queries three times each | p95 < 500 ms |

Not covered yet: the Apple clients' local save and open (Swift `measure`), the web client, concurrency, and sync of a 100k-note vault (Phase 5).

## Results

Times in milliseconds as p50 / p95, durations in seconds.

| Date | Where | Notes | import | rebuild | open | save | list | links | tags | search |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-14 | Claude cloud container, 4 vCPU, 16 GB, PostgreSQL 16 | 2,000 | 51 s | 12.5 s | 9 / 13 | 47 / 59 | 22 / 29 | 14 / 20 | 10 / 18 | 28 / 47 |
| 2026-11-14 | Claude cloud container, 4 vCPU, 16 GB, PostgreSQL 16 | 10,000 | 248 s | 60 s | 9 / 10 | 42 / 55 | 17 / 23 | 12 / 16 | 16 / 23 | 20 / 116 |
| 2026-11-14 | GitHub `ubuntu-latest`, 4 vCPU, PostgreSQL 18 ([run](https://github.com/theonewizard/OpenNote/actions/runs/43547249632)) | 100,000 | 2,416 s | 428 s | 7 / 8 | 47 / 80 | 19 / 22 | 10 / 12 | 60 / 80 | 49 / 393 |

Neither the container nor the GitHub runner is the reference VM, so these numbers are indicative only. At 100,000 notes both targets hold: open p95 is 8 ms (target 200 ms) and search p95 is 393 ms (target 500 ms). The separate search benchmark measured 185 ms over its 20 queries. Search has the least headroom and is the number to watch. Import and rebuild grow about linearly: a 100k-note vault imports in about 40 minutes and rebuilds its index in about 7. The nightly job adds a row's worth of data to its summary every night.

## Findings fixed on the way

- Importing a vault of more than 65,535 notes failed: the import filtered by an `IN` list of every changed id, one PostgreSQL parameter each (R-P8-101).
- Importing even 2,000 notes did not finish in 10 minutes: each commit re-resolved every unresolved link of the vault against every path. Migration `0008` and a targeted re-resolution fixed it (R-P8-102).

Rulings: [.conversations/2026-11-14-performance-validation.md](../../.conversations/2026-11-14-performance-validation.md).
