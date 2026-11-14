# 2026-11-14 — Phase 5 sync server

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Rulings are numbered `R-P5-nnn` and listed with their reasons in [the Phase 5 sync server plan](../docs/superpowers/plans/2026-11-14-phase-5-sync-server-plan.md#rulings-no-owner-decision-needed).

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-14 00:53 | Flemming (project chat) | "Start the development phase 5,6 8 using ubi 10" |
| 2026-11-14 00:53 | Coordinator (relaying) | Phase 5 per docs/ROADMAP.md, starting with the production sync server (P5-01, P5-02, P5-06, P5-07); P5-02 includes streaming large blobs, carried over from Phase 1. Client sync engines come after the server. Phases 6 and 8 run in other threads, and the deployment thread moves the images to UBI 10.3, so any image work must target UBI 10. Merge main often; CodeRabbit is off. |

## Output

- Branch `feature/sync-server` in `.worktrees/sync/` (PR A of the plan): P5-01 endpoints and P5-06 history, migration 0008, tests, regenerated OpenAPI document and clients, docs.
- Branch `feature/resumable-blobs` in `.worktrees/blobs/` (PR B, stacked on PR A): P5-02 resumable chunked uploads and the streaming commit path; nginx body limits for `/api/` (R-P5-009, R-P5-010).

## Notes from other threads

| Time (UTC) | From | Note |
|---|---|---|
| 2026-11-14 01:47 | Coordinator | Migration 0008 is also used by Phase 6 PR #52 and AI PR #37; whichever merges later renumbers and rebases `down_revision`. |
| 2026-11-14 01:49 | Phase 8 thread | PR #56 (P8-01) adds a migration 0008 and edits `Committer._index`, `_recover` and `service.ingest_fs_changes`; whichever merges second rebases. A later PR adds `python -m app.sync.rebuild`. |
