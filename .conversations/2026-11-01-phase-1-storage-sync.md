# 2026-11-01 — Phase 1 implementation (storage engine and sync prototype)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Rulings continue the numbering of [2026-11-01-phase-1-plan.md](2026-11-01-phase-1-plan.md).

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 20:06 | Flemming | "go" |

## How the prompt was read

"go" after the plan merged (pull request #25) and D9–D11 were answered: implement all 16 tasks of the [Phase 1 plan](../docs/superpowers/plans/2026-11-01-phase-1-storage-sync-plan.md) on `feature/phase-1-storage-sync` in `.worktrees/storage/`, without check-ins, ending in one pull request that Flemming merges. Each task was done test-first; every departure from the plan is listed under the plan's Errata and summarised below.

## Rulings

- R136: the plan is executed inline, task by task, with a progress ledger outside the repository (`.superpowers/`, git-ignored) and one fresh whole-branch review at the end.
- R137: Task 13 (pure merge) ran before Task 12, because the commit path calls the merge for stale bases.
- R138: the concurrent-pair rules of sync protocol §6 (stale-note merge, conflict copies, edit wins over delete, later move wins) live in `Committer._plan`, inside the locked transaction; a superseded delete answers status `merged` with a `delete-superseded` problem, since `OpResult` has no superseded status.
- R139: the recovery area for displaced external bytes is `<history_root>/<vault_id>/recovery`, outside the vault on the history volume.
- R140: the prototype's retention window is 100,000 sequence numbers (`RETENTION_SEQ_WINDOW`); `revisions` gained a `size` column because pull entries carry the size.
- R141: the watcher debounces per vault (500 ms of quiet) and each pass is a full scan with a stat cache, because deletes and moves need the whole tree; narrowing it is for Phase 2.
- R142: the simulation harness lives in `backend/tests/integration/sync_sim/` (the plan said `backend/tests/sync_sim/`) to reuse the integration database fixtures; the `Committer` takes an injected clock so I6 can run on a skewed server clock.
- R143: the simulation found four server bugs, each fixed with a test that failed first: a move whose source folder was gone crashed the commit; a move of a file edited on the server's disk now carries the edit along and absorbs it (instead of skipping the move); an absorbed server edit that ends in a conflict now leaves the committed revision at the path and the edit in the conflict copy; a create that lands on an unscanned file of the same name on the server now keeps that file as a separate conflict copy instead of committing it as the new file's second revision. Nine more failing seeds were bugs of the simulated client or the checker. Those nine and the two server-bug seeds (60 and 667) are kept as regression tests.
- R144: CI runs 500 seeds inside the backend `pytest` job (about three minutes) and 10,000 more seeds in a nightly `sync-sim-nightly` job on `main`; `make sync-sim SEEDS=…` runs it locally.
- R145: the final whole-branch review (a fresh reviewer) found two critical and six important issues. Fixed, each with a test that failed first: link resolution leaked across vaults; long file names broke the temp and conflict-copy names; a vault write failing after the commit was later read by the watcher as an edit or delete; one unreadable file stopped every scan; case-only twins flipped the registry; oversized notes were parsed on ingest. Left for later and listed in the status document: a per-vault lock through the vault write (Phase 2 prerequisite), the crash-recovery merge base (a sync protocol §2.3 gap for Flemming), and streaming large blobs (P5-02).

## Output

Pull request from `feature/phase-1-storage-sync`; status in [IMPLEMENTATION_STATUS.md](../docs/IMPLEMENTATION_STATUS.md) and the P1 rows of [ROADMAP.md](../docs/ROADMAP.md).
