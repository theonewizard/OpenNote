# 2026-11-14 — Revert TypeScript 7.0.2 again

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Done in the "Harden deployment and releases" thread, which hit the failure on PR #38; rulings continue its R-P8-0xx numbering.

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-14 23:33 | Claude (decision card to Flemming) | "Revert the TypeScript 7.0.2 merge (#47) that turned the web job red on main?" Recommended: revert. |

## Rulings

- R-P8-036: Dependabot's #47 (TypeScript 6.0.3 → 7.0.2 in `web/`) was merged into `main` at 2026-11-14 23:27 UTC as c1543b8. `npm ci` fails with ERESOLVE: `typescript-eslint` 8.72.2 peers `typescript >=4.8.4 <6.1.0`. That makes the `web` job red on `main` and on every pull request that merges `main` (first seen on #38, run 43653499291). It is the same failure as #5 on 2026-11-01, which #24 reverted (`.conversations/2026-11-01-revert-typescript-7.md`). This is `git revert -m 1 c1543b8`: `web/package.json` and `web/package-lock.json` go back to TypeScript 6.0.3 with the existing `overrides` entry. TS 7 still waits until `typescript-eslint` and `openapi-typescript` support it.
