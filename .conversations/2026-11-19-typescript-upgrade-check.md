# 2026-11-19 — Check for TypeScript 7 readiness with every web build

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Done in the "Harden deployment and releases" thread; rulings continue its R-P8-0xx numbering.

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-19 07:39 | Claude (decision card to Flemming) | "Revert TypeScript 7.0.2 (#72) again and stop Dependabot re-proposing it?" Recommended: revert and add a Dependabot ignore for TypeScript majors. |
| 2026-11-19 07:48 | Flemming | "We should not ignore it, but check it every time we build and skip it if it is still not there. There is a risk ignore will spik the upgrade when it becomes avalible if it is just ignored." |
| 2026-11-19 07:51 | Flemming | "please add this as a rule in the claude.md also" |

## Rulings

- R-P8-037: TypeScript 7.0.2 was merged red a third time (#72, after #5 and #47): `npm ci` fails because typescript-eslint (8.73.0, newest) peers `typescript >=4.8.4 <6.1.0` and openapi-typescript (7.13.0, newest) peers `^5.x`. The revert is #77, from the "Resolve PR conflicts and merge order" thread. No Dependabot ignore rule, per Flemming.
- R-P8-038: A new job in `web.yml`, `TypeScript upgrade check`, runs `scripts/check-typescript-next.sh` with every web run. If the newest TypeScript is on the major already in `package.json`, it leaves a notice. If either peer's newest release rejects the newest TypeScript, it leaves a notice naming the peer range ("skip it if it is still not there"). Once both accept it, it sets the three newest versions in a throwaway `package.json` (overrides entry dropped), runs `npm install`, lint, typecheck, unit tests, build and the client generator, restores `package.json` and the lock file, and leaves a warning: either ready, or which steps fail. The job never fails the run, so it cannot block merges.
- R-P8-039: `CLAUDE.md` section 20 gains "Blocked upgrades": a blocked upgrade never gets a Dependabot `ignore` rule or another permanent skip; it is reverted for now and a check runs with every build, quiet while upstream support is missing and clear once the upgrade is possible.
- Verified locally on Node 26.12.0 with TypeScript 6.0.3 (#77's tree): the notice path prints both peer ranges. With the peer test forced true and `--legacy-peer-deps`, the trial path ran with TypeScript 7.0.2: typecheck, unit tests and build pass, and lint and client generation fail. `package.json` and the lock file were unchanged afterwards.
