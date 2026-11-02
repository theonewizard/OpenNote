# 2026-11-02 — Bookkeeping for Dependabot's bumps (#21, #27, #28, #29)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Rulings continue the numbering of [2026-11-01-phase-1-plan.md](2026-11-01-phase-1-plan.md) (R135); the record this one replaces, written on 2026-11-01 for #23 and closed with it, had reused R125 to R127.

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-01 19:36 | Flemming (project chat) | "go" |
| 2026-11-01 19:37 | Flemming (project chat) | "go for rebase" |
| 2026-11-02 20:01 | Flemming (decision card) | "Follow-up PR", to "Where should the versions.md and constraints bookkeeping for Dependabot's #27, #28 and #29 go?" (the other option: on their branches, as on 2026-11-01) |

The first two answer a project-chat note that Dependabot's #22 (npm group) was green while #21 (web builder image) and #23 (pip group) were behind `main` after the #24 revert: bring the three up to date, merge nothing. Dependabot's Monday run of 2026-11-02 (16:17 UTC) then closed #22 and #23 as superseded by #28 and #29 before they were merged, and opened #27 (a new `ubi-minimal:9.8` build for all four Containerfiles); #21 stayed open. Flemming merged #21 (`04c0451`), #29 (`4ce4c03`), #28 (`a84a95d`) and #27 (`4b22060`) between 20:02 and 20:05 UTC.

## Rulings

- R136: each Dependabot branch got a merge of `origin/main` pushed to it, not an `@dependabot rebase` comment and not a rebase. The comment cannot be issued from this container: its egress proxy rewrites the `@dependabot` mention on the way out (a middle dot is inserted around it), so Dependabot never sees the command; two such comments were posted and deleted again. A rebase would rewrite a branch this session did not create. Cost if wrong: none left, the branches are closed or merged.
- R137: #21 also moved the root `.nvmrc` from 26.12.0 to 26.13.0 (the release of 2026-10-28 that makes v26 an LTS line, codename "Lithium") because versions.md ties the builder image to "exactly the release in `.nvmrc`"; the `engines` range in `web/package.json` (`>=26.12.0 <27`) still holds and was left alone. Its versions.md rows (Node.js, npm, builder image) rode on #21 itself and are on `main`. Cost if wrong: one line in `.nvmrc` to put back.
- R138: `backend/constraints.txt` is regenerated with `make constraints` (Python 3.14.6, pip 26.1.2) after the pip bumps instead of trusting Dependabot's line-by-line edits. Dependabot now bumps the pins it finds in the file (#29 moved opentelemetry-api, pydantic-core and websockets as well as the seven direct ones), but only a clean resolve shows what a fresh install brings in: today it also moves anyio 4.15.1 to 4.16.0, which #29 did not, and the CI `constraints` job checks satisfiability only. The versions.md rows for the seven direct packages are updated from PyPI's release dates, and two rows that were already behind before these bumps (SQLAlchemy 2.1.6, alembic 1.20.1) are fixed in the same pass.
- R139: the bookkeeping lands as one follow-up pull request right after the Dependabot merges, not on the Dependabot branches, per Flemming's card choice: the Monday run replaces an unmerged grouped pull request when a newer version appears and takes hand edits on its branch along (#22 and #23 today). docs/development/setup.md says so now. Cost if wrong: a window between a Dependabot merge and its follow-up in which versions.md and the transitive pins lag `main`.

## Output

Branch `docs/dependabot-bookkeeping` in `.worktrees/dependabot-bookkeeping/`: one pull request to `main` with the versions.md rows for #27, #28 and #29 (plus SQLAlchemy and alembic), the regenerated `backend/constraints.txt`, the setup.md paragraph and this record. Nothing merged from this side.
