# 2026-10-18 — Node.js 26 and TypeScript

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Continues the thread of [2026-10-17-phase-0-foundation.md](2026-10-17-phase-0-foundation.md) after the Phase 0 merge.

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 17:26 | Flemming | "go", answering "ready for your squash merge" on the Phase 0 pull request (#3) → squash-merged as `ad3d007` |
| 17:49 | Flemming | Chose "Drop swift" on the decision card "Handle Dependabot's Swift updater, which cannot read tools version 6.4, how?" → pull request #7, squash-merged as `f8aa89a` |
| 17:50 | Flemming | "Bunp to node 26 and ts 7" |
| 20:48 | Flemming | Chose "6.0.3 with override" on the decision card "Ship which TypeScript in the Node 26 pull request?", two hours after merging pull request #8 with 5.9.3 → branch `chore/typescript-6`, a second pull request |

## How the prompt was read

- "node 26": move the whole web toolchain to Node.js 26.12.0 in one change (`.nvmrc`, `engines`, `@types/node`, the `opennote-web` builder image, the docs) instead of merging Dependabot's separate pull requests #4 (`@types/node` 26.6.5) and #6 (builder image `node:26.12.0-trixie-slim`), which Dependabot closes itself once `main` carries the versions.
- "ts 7": TypeScript 7.0.2 (Dependabot #5) and the bridge release 6.0.3 were both tried on the branch and neither could ship; see R105. The choice is put to Flemming on a decision card, with 5.9.3 kept meanwhile.
- "6.0.3 with override": the card's option said `legacy-peer-deps=true` in `web/.npmrc`, so npm would stop checking peer ranges for every package. The change uses an npm `overrides` entry on the one conflicting peer edge instead (R109): the same outcome, TypeScript 6.0.3 installed by `npm ci`, with less switched off than the card described.

## Rulings

- R105: TypeScript stays at 5.9.3 for now. With 7.0.2 installed on Node.js 26.12.0, `tsc -b --noEmit`, vitest and `vite build` pass, but `npm run lint` exits 2 with `Error: typescript-eslint does not support TS 7.0` (typescript-eslint 8.71.2, peer `<6.1.0`; no newer line on npm, `canary` is 8.71.3-alpha.13) and `scripts/gen-clients.sh` crashes inside openapi-typescript 7.13.0 (`TypeError: Cannot read properties of undefined (reading 'createKeywordTypeNode')`: the 7.0.2 package ships no `lib/typescript.js`; openapi-typescript has no 8.x, `next` is 7.0.0-rc.1). With 6.0.3 every check passes and `schema.d.ts` is byte-identical, but `npm ci` fails with `ERESOLVE` on openapi-typescript's peer `^5.x` (only `npm install typescript@6.0.3` tolerates it with a warning), so CI and the `opennote-web` image build would fail. Shipping 7 would mean disabling the lint and client-drift checks; shipping 6 would mean `legacy-peer-deps` or `overrides` in `web/`, which versions.md rules out. Both are Flemming's call (`CLAUDE.md` §2: disabling checks, bypassing controls), asked on a decision card. Cost if wrong: one line in `web/package.json`.
- R106: the lockfile is `main`'s lock plus one direct change (`npm install --save-exact @types/node@26.6.5` on npm 11.20.0), not a regenerated one, so no transitive pin moves. `npm install --package-lock-only` on npm 11.20.0 would also add `inBundle` entries for `@tailwindcss/oxide-wasm32-wasi`'s bundled dependencies; that churn is left out.
- R107: the builder image digest `sha256:0d1e3358…` was read from the Docker Hub tag API on 2026-10-18; Dependabot's pull request #6 carries the same digest.
- R108: Node.js 26 is adopted ten days before it enters Active LTS (2026-10-28 in the nodejs/Release schedule); v24 enters Maintenance on 2026-10-20, so waiting would leave the project on a maintenance line. versions.md records both dates.
- R109: TypeScript 6.0.3 ships with `"overrides": {"openapi-typescript": {"typescript": "$typescript"}}` in `web/package.json`, not `legacy-peer-deps`. Both make `npm ci` accept 6.0.3 (checked in a scratch copy on npm 11.20.0), but the override relaxes only openapi-typescript's `^5.x` edge, keeps every other peer check (typescript-eslint's `<6.1.0` still blocks 6.1 until it is supported), follows the pinned release through `$typescript`, and lives in `package.json`, which the `opennote-web` builder copies; `legacy-peer-deps` in `web/.npmrc` would not reach that builder (its `npm ci` failed with `ERESOLVE` without the file in the same scratch test) and switches peer checks off for every package. Supersedes R21's "no overrides". Cost if wrong: one entry in `web/package.json`.
- R110: pull request #8 was merged by Flemming as merge commit `0268014`, not squash-merged as the Output line below first said (CodeRabbit flagged the wording while the pull request was open); the line now records what happened.

## Output

Branch `chore/node-26-ts-7` in `.worktrees/toolchain/`: pull request #8 (Node.js 26.12.0, TypeScript 5.9.3), merged by Flemming on 2026-10-18 at 18:44 UTC as merge commit `0268014`. Branch `chore/typescript-6` in the same worktree: a second pull request to `main` (TypeScript 6.0.3 with the override, R109), to be merged after review and green CI.
