# 2026-11-14 — Phase 8: performance validation (P8-01)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Done in the "Finish Phase 8 production hardening" thread. P8-04, P8-06 and P8-08 belong to the "Harden deployment and releases" thread (rulings R-P8-001 to R-P8-032); this thread's rulings start at R-P8-100 so the two never collide.

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-14 00:53 | Flemming | Start the development phase 5,6 8 using ubi 10 |
| 2026-11-14 00:53 | Coordinator | Phase 8 thread: the remaining Phase 8 items per `docs/ROADMAP.md`, on UBI 10. P8-04, P8-06 and P8-08 are done in the "Harden deployment and releases" thread, which is also moving all four images to `ubi10/ubi-minimal:10.3` (PR #51): build on top of it once it merges. RHEL 10 needs an x86-64-v3 CPU. Phases 5 and 6 have threads of their own. |

## Scope

Remaining Phase 8 items: P8-01 (performance), P8-02 (security testing), P8-03 (accessibility), P8-05 (disaster recovery), P8-07 (documentation), P8-09 (beta). Done here as one pull request each. Not done by this thread, because they need Flemming or Phase 5: the external security review (P8-02), VoiceOver testing on Apple hardware (P8-03), benchmark numbers on the reference hardware of testing-strategy §6 (P8-01), and the beta program (P8-09, after M5 and P8-01 to P8-08).

## Rulings

### P8-01 performance (branch `feature/performance-validation`)

- R-P8-100: the benchmark is a slow-marked pytest next to the 100k search benchmark (`tests/integration/api/test_vault_perf.py`, not a new `tests/performance` tree), so it reuses the API fixtures. Unlike the search benchmark it writes nothing into the tables: 100,000 Markdown files (~1.5 KB, frontmatter tags, two wikilinks, a task in every tenth) are written into a vault folder and imported by the vault watcher's first full scan, the path an existing Obsidian vault takes. Then `rebuild_index`, then in-process (ASGI) timings of open, save, list, links, tags and search. Asserted targets: open p95 < 200 ms, search p95 < 500 ms (design §15.14); the rest is recorded. `make benchmark` runs both slow benchmarks; a nightly `benchmark-nightly` job in `backend.yml` runs it and puts the JSON in the job summary and an artifact. Settings use the `OPENNOTE_TEST_` prefix because the test conftest clears every other `OPENNOTE_*` variable.
- R-P8-101: first finding: importing a vault of more than 65,535 notes failed. `ingest_fs_changes` and `Committer.recover` filtered `files` and `revisions` with an `IN` list of every changed id, one bind parameter each, and PostgreSQL refuses more than 65,535; the watcher logged the error and retried forever. Both now pass the ids as one array parameter (`col = ANY(:ids)`, helper `app.core.db.uuid_array`). Regression test with 70,000 ids.
- R-P8-102: second finding: the import of even 2,000 notes did not finish in 10 minutes. Every indexed note re-resolved every unresolved link of its vault, and each resolution compared the link with every path (O(links × paths) per commit; the "Known limits" entry said P8-01 would measure it). Now a commit re-resolves only the links its file can change: those pointing at it (it moved or was deleted) and those whose target names its file name, which is the only way a file can become a link's answer. Migration `0008` adds `note_links.target_key` (the case-folded file name the target names, computed in Python because SQL `lower()` is not Unicode case folding) and indexes on it, on `note_links.resolved_file_id` and on the case-folded file name of `files.path_key`; resolution loads only the files with a matching name and writes only changed answers, in one executemany. Attachments now trigger the re-resolution themselves (before, a link to a new attachment resolved at the next note commit). Links indexed before 0008 have a NULL key and keep the old behaviour (re-resolved on every commit) until their note is indexed again or the index is rebuilt. Test: a sequence of commits (attachment added, a better match added, deleted, the remaining match moved away) gives the answers a full resolution gives.
