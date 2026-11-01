# 2026-11-01 — Revert of the TypeScript 7.0.2 bump (#5)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Rulings continue the numbering of [2026-11-01-trivy-unfixed-report.md](2026-11-01-trivy-unfixed-report.md).

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 16:58 | GitHub (no user prompt) | Dependabot's pull request #5, "Bump typescript from 6.0.3 to 7.0.2 in /web", was merged into `main` as `e34ddb9` with three red checks on its head `1d0ee34`: `web` (lint, typecheck, test, build, e2e), `backend` (openapi drift) and `containers` (build, run, scan). The architecture thread, which owns the toolchain bumps, acted on the merge event |

## How the event was read

- Flemming had ruled "Bump to node 26 and ts 7" on 2026-10-18; TypeScript 7 was then found blocked (versions.md, typescript row; R105, R109) and `main` went to 6.0.3 with one npm override for `openapi-typescript`'s peer range (#9). #5 stayed open as the reminder. Merging it does not change what blocks it.
- All three red checks fail at the same line, `npm ci` in `web/` (directly in `web`, through `make bootstrap` in the openapi drift job, and in the `opennote-web` builder stage): `ERESOLVE ... peer typescript@">=4.8.4 <6.1.0" from typescript-eslint@8.72.0 ... Found: typescript@7.0.2`. The override in `web/package.json` relaxes `openapi-typescript`'s peer only, as #9 intended; `typescript-eslint` has no override and refuses TypeScript 7.

## Rulings

- R122: revert the merge (`git revert -m 1 e34ddb9`) instead of widening the override to `typescript-eslint`. An override would let `npm ci` pass but would run typescript-eslint 8.72 against a compiler it does not support (its peer range stops at 6.1.0 in 8.72.1, published 2026-10-29, and no release past it exists), and `openapi-typescript` 7.13.0 (June 2026, peer `^5.x`) crashed generating the client under TypeScript 7 on 2026-10-18 (R105). The revert restores `web/package.json` and `web/package-lock.json` byte for byte to their state at `0af6f6a` (the #20 merge), whose `web`, `openapi drift` and `containers` checks were green on #20's head `44cc5f2`. Cost if wrong: Flemming merges the bump again when its blockers are gone, which is one click.
- R123: no `ignore` rule for TypeScript majors is added to `dependabot.yml`. Dependabot will open the 7.0.2 bump again once `main` is back on 6.0.3; that pull request is the reminder Flemming kept #5 open for. What stops a repeat of today is the branch protection in his settings list (required checks on `main`, docs/development/workflow.md), not a Dependabot rule.
- R124: verification. The two reverted files are identical to `0af6f6a` (`git diff --cached --stat 0af6f6a -- web/package.json web/package-lock.json` is empty), and on the cloud container with Node 26.12.0: `npm ci`, `npm run lint`, `npm run typecheck` and `npm run build` all pass on the reverted tree (the Playwright end-to-end tests were left to CI).. The pull request's own `web`, `backend` and `containers` runs are the live proof.

## Output

Branch `revert/typescript-7` in `.worktrees/toolchain/`: a pull request to `main` reverting `e34ddb9`, this record included.
