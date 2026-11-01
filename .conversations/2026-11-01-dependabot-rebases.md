# 2026-11-01 — Bringing Dependabot's #21, #22 and #23 up to date with `main`

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Rulings continue the numbering of [2026-11-01-revert-typescript-7.md](2026-11-01-revert-typescript-7.md).

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 19:36 | Flemming (project chat) | "go" |
| 19:37 | Flemming (project chat) | "go for rebase" |

Both answer a project-chat note that Dependabot's #22 (npm minor and patch group in `web/`) was green while #21 (web builder image `node:26.13.0-trixie-slim`) and #23 (pip minor and patch group in `backend/`) were behind `main` after the #24 revert. The second prompt narrows the first: bring the three branches up to date, merge nothing; Flemming merges.

## Rulings

- R125: each Dependabot branch gets a merge of `origin/main` pushed to it, not an `@dependabot rebase` comment and not a rebase. The comment cannot be issued from this container: its egress proxy rewrites the `@dependabot` mention on the way out (a middle dot is inserted around it), so Dependabot never sees the command; two such comments were posted and deleted again. A rebase would rewrite a branch this session did not create. After a push by someone else Dependabot stops updating the branch on its own, which is wanted here because each branch now also carries the hand edits of the next two rulings. Cost if wrong: Dependabot opens a fresh pull request for the same bump and these three are closed.
- R126: #21 also moves the root `.nvmrc` from 26.12.0 to 26.13.0 (the LTS release of 2026-10-28, codename "Lithium") because versions.md ties the builder image to "exactly the release in `.nvmrc`"; the `engines` range in `web/package.json` (`>=26.12.0 <27`) still holds and is left alone. The Node.js, npm and builder-image rows of versions.md move with it (#22 had its typescript-eslint and @types/node rows updated the same way). Cost if wrong: one line in `.nvmrc` to put back.
- R127: for #23, `backend/constraints.txt` is regenerated with `make constraints` (Python 3.14.6, pip 26.1.2), as docs/development/setup.md asks of whoever lands a pip bump, instead of keeping Dependabot's five edited lines. A clean install today also resolves anyio 4.16.0 (was 4.15.1), opentelemetry-api 1.45.2 (1.45.1) and websockets 17.4 (17.3), so the regenerated file moves those three transitive pins too; the CI `constraints` job only checks that the file is satisfiable, so it would not have noticed. The seven versions.md rows the bump touches (fastapi, pydantic, pydantic-settings, starlette, pytest, ruff, mypy) are updated from PyPI's release dates. Two rows were already stale before #23 and are left for a separate change: SQLAlchemy (row 2.1.5, requirements 2.1.6) and alembic (row 1.20.0, requirements 1.20.1).

## Output

One extra commit on each Dependabot branch, pushed to its existing pull request: #22 (`dd6f852`, versions.md rows), #21 (`.nvmrc` and versions.md rows) and #23 (constraints.txt, versions.md rows and this record). Nothing merged from this side.
