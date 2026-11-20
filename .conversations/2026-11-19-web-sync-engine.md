# 2026-11-19 — Web sync engine (P5-04)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Done in the "Build web sync engine" thread; plan and rulings R-W5-001..012 in `docs/superpowers/plans/2026-11-19-web-sync-engine-plan.md`.

## Prompts

- Flemming chose to build the web and Apple sync engines in parallel threads after the sync server (PR #55) merged on 2026-11-19; this thread builds the web engine in `web/`.
- Flemming, 2026-11-19 08:10 UTC (in the Phase 5 thread): "Need CI to run so it is not ready for review". The pull request stays a draft until CI is green on its head.

## Notes

- P3-08 (IndexedDB cache and outbox) was a prerequisite and not built; it lands in the same change.
- Verified by hand against a local API (PostgreSQL 16, Valkey via redis-server, uvicorn, `vite` dev proxy, Chromium): a browser edit is committed through push; an edit by another session reached the open editor about 250 ms later through the SSE hint; an offline edit and a concurrent edit of another line were merged by the server; a concurrent edit of the same line became a conflict copy with an open conflict and a notice in the editor; a 20 MiB blob resumed from `Upload-Offset` after its first chunk.
- That run found two bugs, both fixed before the pull request: the engine asked `/api/v1/users/me` (the route is `/api/v1/me`), and a pull after a conflict cleared the conflict notice.
- Seen on the server, not changed here: a conflict copy of a note keeps the original's frontmatter `id`, so two files carry the same `id`.
