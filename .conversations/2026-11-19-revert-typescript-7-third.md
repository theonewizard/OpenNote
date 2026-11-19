# Revert TypeScript 7.0.2 again (#72), 2026-11-19

## Prompt (Flemming, 2026-11-19 07:37 UTC)

> Pull request conflicts in the repos please fix it and prepare to merge them in correct order.

## What happened

Dependabot's #72 (TypeScript 6.0.3 to 7.0.2) was merged on 2026-11-19 07:34 UTC as 3775c87.
main e3626b8 then failed the web job at `npm ci` with ERESOLVE: typescript-eslint 8.72.2 peers
typescript `<6.1.0`. Every PR that runs `npm ci` inherits the failure, so the conflict pass
cannot show green PRs until main is fixed.

This branch is `git revert -m 1 3775c87`: web/package.json back to typescript 6.0.3 (the
openapi-typescript `overrides` entry from #9 is untouched) and the matching package-lock.json.
Same fix as #24 and #66. TypeScript 7 still waits for typescript-eslint and openapi-typescript
to accept it; Dependabot will propose it again and that PR should stay open as the reminder.
