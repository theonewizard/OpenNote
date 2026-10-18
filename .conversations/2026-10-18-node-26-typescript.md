# 2026-10-18 — Node.js 26 and TypeScript

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Continues the thread of [2026-10-17-phase-0-foundation.md](2026-10-17-phase-0-foundation.md) after the Phase 0 merge.

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 17:26 | Flemming | "go", answering "ready for your squash merge" on the Phase 0 pull request (#3) → squash-merged as `ad3d007` |
| 17:49 | Flemming | Chose "Drop swift" on the decision card "Handle Dependabot's Swift updater, which cannot read tools version 6.4, how?" → pull request #7, squash-merged as `f8aa89a` |
| 17:50 | Flemming | "Bunp to node 26 and ts 7" |

## How the prompt was read

- "node 26": move the whole web toolchain to Node.js 26.12.0 in one change (`.nvmrc`, `engines`, `@types/node`, the `opennote-web` builder image, the docs) instead of merging Dependabot's separate pull requests #4 (`@types/node` 26.6.5) and #6 (builder image `node:26.12.0-trixie-slim`), which Dependabot closes itself once `main` carries the versions.
- "ts 7": TypeScript 7.0.2 (Dependabot #5) and the bridge release 6.0.3 were both tried on the branch and neither could ship; see R105. The choice is put to Flemming on a decision card, with 5.9.3 kept meanwhile.

## Rulings

- R105: TypeScript stays at 5.9.3 for now. With 7.0.2 installed on Node.js 26.12.0, `tsc -b --noEmit`, vitest and `vite build` pass, but `npm run lint` exits 2 with `Error: typescript-eslint does not support TS 7.0` (typescript-eslint 8.71.2, peer `<6.1.0`; no newer line on npm, `canary` is 8.71.3-alpha.13) and `scripts/gen-clients.sh` crashes inside openapi-typescript 7.13.0 (`TypeError: Cannot read properties of undefined (reading 'createKeywordTypeNode')`: the 7.0.2 package ships no `lib/typescript.js`; openapi-typescript has no 8.x, `next` is 7.0.0-rc.1). With 6.0.3 every check passes and `schema.d.ts` is byte-identical, but `npm ci` fails with `ERESOLVE` on openapi-typescript's peer `^5.x` (only `npm install typescript@6.0.3` tolerates it with a warning), so CI and the `opennote-web` image build would fail. Shipping 7 would mean disabling the lint and client-drift checks; shipping 6 would mean `legacy-peer-deps` or `overrides` in `web/`, which versions.md rules out. Both are Flemming's call (`CLAUDE.md` §2: disabling checks, bypassing controls), asked on a decision card. Cost if wrong: one line in `web/package.json`.
- R106: the lockfile is `main`'s lock plus one direct change (`npm install --save-exact @types/node@26.6.5` on npm 11.20.0), not a regenerated one, so no transitive pin moves. `npm install --package-lock-only` on npm 11.20.0 would also add `inBundle` entries for `@tailwindcss/oxide-wasm32-wasi`'s bundled dependencies; that churn is left out.
- R107: the builder image digest `sha256:0d1e3358…` was read from the Docker Hub tag API on 2026-10-18; Dependabot's pull request #6 carries the same digest.
- R108: Node.js 26 is adopted ten days before it enters Active LTS (2026-10-28 in the nodejs/Release schedule); v24 enters Maintenance on 2026-10-20, so waiting would leave the project on a maintenance line. versions.md records both dates.

## Output

Branch `chore/node-26-ts-7` in `.worktrees/toolchain/`, one pull request to `main`, squash-merged after review and green CI.
