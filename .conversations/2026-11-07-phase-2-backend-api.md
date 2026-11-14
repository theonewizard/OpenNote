# 2026-11-07 — Phase 2 backend API

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Rulings of this phase are numbered `R-P2-nnn` (collision rule proposed by the planning thread on 2026-11-07, so parallel threads do not race for the shared R sequence, which ended at R152).

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-07 15:01 | Flemming (project chat) | "Run most of the phases in parallel so it is developed quickly." |
| 2026-11-07 15:01 | Coordinator (relaying) | Implement Phase 2 per the architecture spec, the roadmap and the status doc; first the per-vault lock held through the vault write; keep changes scoped to Phase 2 and rebase often, since other threads work on later phases at the same time. |
| 2026-11-07 15:02 | Planning thread | Asked for a contract-first pull request (the full v1 OpenAPI surface with stub routes and regenerated clients) so the web and Apple threads can start; proposed one migration per pull request and per-workstream ruling numbers. |
| 2026-11-07 15:23 | Coordinator, AI thread | PR #37 also adds Alembic migration 0006; whichever merges second renumbers. The AI thread asked for `embed_vault_job.send(vault_id)` after successful commits once its PR is on `main`. |
| 2026-11-07 15:32 | Apple core thread | `read_properties` raised on an impossible date and returned non-JSON tagged scalars; asked that non-finite floats keep their source text. Fixed (0c8d579, 3fad031). |
| 2026-11-07 15:04 | Web shell/editor thread | Builds against API contract §3 shapes (vault, note, content as `text/markdown` with `ETag`/`If-Match`, `{items, next_cursor}`, `GET /folders?vault_id=`) and asked for the contract pull request number. |
| 2026-11-07 20:57 | Web shell/editor thread | After the merge (main 56ed844): registering an existing folder as a vault lists its folders but no notes; nothing calls the indexer. Cause: no process runs the vault watcher. Branch `fix/vault-watcher` adds `python -m app.vaults` (one instance per database, advisory lock), deploys it in Compose, Helm and Kustomize, and makes `ingest_fs_changes` read disk and registry under the vault lock so a write another process has not finished is not reverted. Where it runs was put to Flemming on a card (recommended: its own process). |
| 2026-11-09 15:36 | Flemming (decision card) | Chose "Trust the web proxy only" for the client IP behind the web proxy (R-P2-010). Branch `fix/forwarded-allow-ips`: Compose pins web to `OPENNOTE_WEB_ADDRESS` in `OPENNOTE_NETWORK_SUBNET` and sets the api's `FORWARDED_ALLOW_IPS` to it; Helm value `trustedProxies` (schema refuses `*`). |

## Rulings

R-P2-001 to R-P2-009 are listed with their reasons in [the Phase 2 plan](../docs/superpowers/plans/2026-11-07-phase-2-backend-api-plan.md#decisions-taken-in-this-plan-rulings-no-owner-decision-needed).

Departures found while implementing are in the plan's Errata.

## Output

- Branch `feature/phase-2-contract` in `.worktrees/api/`: the Phase 2 plan, this record, and Task 1 (the v1 contract with stub routes answering 501, regenerated clients).
- Branch `feature/phase-2-api` in `.worktrees/api/`: the per-vault lock (Task 2), the foundation (Task 3), the five streams merged from `feature/phase-2-{auth,notes,attachments,search,audit}` (Tasks 4 to 8), contract tests and docs (Task 9): the implementation pull request.
