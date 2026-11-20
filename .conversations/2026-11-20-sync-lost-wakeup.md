# Web sync: a save requested as a sync finished waited 60 s (2026-11-20)

Thread: Fix failing checks and conflicts on open PRs. Requested by Flemming.

## Prompts

- Flemming: "still pull requests with failed checks and also conflicts". The coordinator asked to fix the red web e2e test seen on #54 (introduced with the web sync engine, #84) rather than leave it red.

## Findings

- The failing test was `accessibility.spec.ts` › "a note can be found, opened, edited and saved with the keyboard alone": after Ctrl+S, no push reached the fake server within 10 s.
- Cause: `SyncEngine.sync()` returns the running promise and sets `again` when a run is in progress. The pass loop checks `again` only between passes; after the last pass the run still awaits `setStatus(vaultId, "idle")` before it leaves `running`. A request in that gap (the first sync finishing just as the user saves) was dropped until the next 60 s timer tick. Slow CI runners hit the gap; a local machine rarely does.

## Output

- `web/src/sync/engine.ts`: when a run ends, a request that came after its last pass starts a new run.
- Regression test in `web/tests/unit/sync-engine.test.ts` (fails without the fix).
- Verified: vitest 60/60, tsc, eslint, Playwright suite repeated 260 times locally with no failures.
