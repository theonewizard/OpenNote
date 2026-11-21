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

## Follow-up: OpenAPI drift after #82 and #53 (2026-11-20)

- Flemming merged #82 (Swift nullable fix in the OpenAPI export) and #53 (rename endpoint) within seconds of each other. Each was green alone, but #82's export rewrites the nullable `If-Match` header that #53 added, so main's committed contract drifted. Branch `fix/openapi-drift-after-53` is the output of `make openapi` on main (be71a26); no backend change.

## Follow-up: versions.md after #86 (2026-11-21)

- Flemming merged Dependabot's #86 (npm minor and patch group) at 03:26 UTC after this thread resolved its conflicts. Per the Dependabot policy (docs/development/setup.md), the versions.md rows land in a follow-up PR. Branch `docs/versions-after-86` updates every Web (npm) row that disagreed with `web/package.json` (the 7 from #86 plus 6 from earlier Dependabot merges that never got their rows: vite's plugin, tailwindcss pair, vitest, globals, jsdom). Release dates from registry.npmjs.org. The multi-package CodeMirror row is unchanged.
