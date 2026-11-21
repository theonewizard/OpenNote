# Component tiers: frontend, middleware, backend

Status: assessment of main at 2f14f9a (2026-11-21). The diagram is
[opennote-components.drawio](opennote-components.drawio) (open it in draw.io or diagrams.net).
Findings are numbered V1 to V9 in the diagram and below; actions A0 to A8 are proposals to plan,
none are implemented.

## Tiers as used here

| Tier | What belongs there | OpenNote components |
|---|---|---|
| Frontend | Code that runs on the user's device or in their browser | Web client (`web/`), Apple apps and Swift packages (`apple/`), web clipper (`clipper/`); Obsidian or any editor working on the vault is an external actor |
| Middleware | Edge, identity, transport, messaging and the process runtimes that host the domain code | `opennote-web` nginx (SPA + reverse proxy), `opennote-api` uvicorn with `app.api` (routers, auth dependencies, rate limits, RFC 9457, ETag/If-Match, idempotency, SSE), `app.auth`, Valkey (Dramatiq broker + change-hint pub/sub), the `worker` process (`app.workers`) and the `watcher` process (`python -m app.vaults`) |
| Backend | Domain logic and state | Domain packages `app.sync`, `app.vaults`, `app.notes`, `app.search`, `app.tasks`, `app.calendar`, `app.attachments`, `app.imports`, `app.ocr`, `app.ai`, `app.core`; PostgreSQL + pgvector, the vault filesystem (authoritative), the history store, `opennote-backup`; external OIDC IdP, AI providers, Tesseract |

## Verdict: is it split today?

**Deployment and process level: yes.** Each tier runs as its own containers: `opennote-web`
(nginx), `opennote-api` image started three ways (`api`, `worker`, `watcher`),
`opennote-valkey`, `opennote-postgres`, PVCs for vaults and history, and the backup job. Compose,
Helm, Kustomize and the OpenShift overlay all keep that shape.

**Frontend versus the rest: yes, cleanly.** The clients share no code with the server. The only
coupling is the committed contract `docs/api/openapi.json`, from which the TypeScript and Swift
clients are generated and checked in CI. The Apple side is layered well (Core, Storage, Sync, API,
Editor packages under thin app targets). The web client is small and follows the same pattern
(generated client, sync engine, editor, feature components). No action is proposed for the
frontend.

**Middleware versus backend inside `backend/app`: no.** It is one Python package, which is what
ADR-0003 asks for, but the layering inside it is not explicit and leaks both ways. That is the
part to split. The split is in-process module layering, not separate services: ADR-0003 (modular
monolith) stays, and none of the actions below adds a deployable.

## Findings

| # | Finding | Evidence |
|---|---|---|
| V1 | Routers hold domain logic and SQL, so `app.api` is not a thin transport layer. `app.attachments` is an empty package; all attachment logic is in the router. | `app/api/notes.py` (882 lines: loading, templates, restore, SQL), `app/api/folders.py` (fd-relative `mkdir`/remove on the vault), `app/api/attachments.py` (type sniffing, byte ranges, history streaming), `app/api/vaults.py` (membership rules); 13 router modules run SQL directly |
| V2 | The commit orchestration lives in the API layer, and the watcher process imports it from there. The API also reaches into a private lock. | `app/api/deps.py` `Committers` and `commit()`; `app/vaults/__main__.py` imports `app.api.deps.Committers`; `deps.commit` calls `committer._vault_lock()` |
| V3 | A domain module imports the API layer. | `app/search/notes.py` imports `app.api.schemas` and `app.api.notes.load_note_rows`, `note_query` |
| V4 | `app.core` depends on FastAPI and on the auth dependency layer, so the bottom layer is HTTP-aware. | `core/audit.py` imports `app.auth.dependencies.Principal` and `fastapi.Request`; `core/problems.py` and `core/db.py` import FastAPI |
| V5 | **Functional gap caused by V2.** AI embedding and OCR are enqueued only from `api/deps.commit`, so only REST writes trigger them. Sync pushes (`api/sync.py` push calls `committer.commit` directly) and on-disk edits ingested by the watcher never enqueue a job; they are picked up only when a later REST write in the same vault enqueues the vault-wide job. A user who only syncs from the Apple app or edits in Obsidian gets no OCR text and no embeddings. `app/ai/jobs.py` documents "whatever changes a note enqueues `embed_vault_job`", which is not true today. | `grep request_embedding\|request_ocr` finds only `app/api/deps.py` |
| V6 | Modules read and write each other's tables, against ADR-0003 "never through each other's tables". | `app.sync` uses `notes.models` and `auth.models`; `app.search` uses `notes`, `ocr` and `sync` models; `app.ai` and `app.ocr` use `notes` and `vaults` models; `notes.index` writes `tasks.models.TaskRow` |
| V7 | Package-level import cycles. | `vaults` and `sync` (via the watcher entrypoint `vaults/__main__.py`); `notes` and `tasks` (`notes.index` calls `tasks.parse`, `tasks.parse` uses `notes.document`); `core` and `auth` (V4) |
| V8 | Architecture documents disagree with the code. | ADR-0003 says derived indexes are updated asynchronously by the worker; `sync/commit.py` `Committer._index` does it synchronously after each commit, in its own transaction. ADR-0003 names a separate `ai` process and image; AI jobs run in the general worker. ADR-0013 says WebSocket hints; the code uses SSE (R-P5-004). |
| V9 | Nothing enforces boundaries, so V1 to V7 can grow unnoticed. | No import contract test in `backend/tests` or CI |

## Target layering

```text
entrypoints  app.api (HTTP), app.workers (jobs), app.watcher (new home of python -m app.vaults)
     |        transport only: parse, authenticate, map errors and schemas
     v
domain       app.sync, app.vaults, app.notes, app.search, app.tasks, app.calendar,
             app.attachments, app.imports, app.ocr, app.ai, app.auth (non-HTTP parts)
     |        service functions; each table has one owning module for writes
     v
core         settings, engines, logging; no FastAPI, no other app package
```

Rules: a domain package never imports `app.api`, `fastapi` or `starlette`; `app.core` imports no
other `app` package; no package-level cycles. Cross-module reads for query paths (search joining
notes, OCR text and revisions) are allowed when listed in ADR-0003; writes go through the owning
module.

## Planned actions

Each action is one PR, keeps behaviour unchanged unless it says otherwise, and runs the full
backend suite. A0 goes first so every later PR shrinks a measured list.

| # | Action | Fixes | Notes |
|---|---|---|---|
| A0 | Add `backend/tests/unit/test_layering.py`: parse every module under `backend/app` with `ast` and fail on the forbidden edges above and on package cycles. Start with an explicit allowlist of today's violations so CI stays green; each later PR deletes its lines. | V9 | Standard library only (no import-linter dependency). About 60 lines. |
| A1 | Move the AI and OCR enqueue into the commit path: register them on the `Committer` `on_commit` callback next to the change-hint publisher, so REST, sync push and watcher commits all enqueue. Remove the calls from `api/deps.commit`. | V5 | **Behaviour change** (the fix). Tests: a sync push and a watcher ingest each enqueue `embed_vault_job` and `ocr_vault_job` when configured. Can ship before A2 if wanted. |
| A2 | Move `Committers` and the revision-checked commit from `app/api/deps.py` to `app/sync` (for example `app/sync/committers.py`), and give `Committer` a public `commit(..., expected_revision=)` so nothing outside `app.sync` touches `_vault_lock()`. `api/deps.py` keeps only request plumbing. | V2 | Watcher and API both import from `app.sync`. |
| A3 | Move the watcher entrypoint from `app/vaults/__main__.py` to `app/watcher/__main__.py` (`python -m app.watcher`) and update Compose, Helm, Kustomize and docs. | V7 (vaults and sync) | Process command changes; keep `python -m app.vaults` as an alias for one release so existing deployments keep starting. |
| A4 | Move `note_query`, `load_note_rows` and the note row assembly from `app/api/notes.py` into `app.notes` (for example `app/notes/query.py`) returning domain objects; the routers and `app.search` map to `app.api.schemas`. | V3, part of V1 | |
| A5 | Make `app.core` HTTP-free: move `core/problems.py` and the request-scoped DB dependency to `app.api`; move `Principal` to a FastAPI-free module (`app/auth/principal.py`), re-exported from `app.auth.dependencies`; `core.audit` takes a client address string instead of a `Request`. | V4, V7 (core and auth) | |
| A6 | Thin the routers, one module per PR, largest risk first: attachments (fill `app.attachments` with sniffing, byte ranges and history streaming), folders (vault fd operations into `app.vaults.fsio`, folder service into `app.notes`), notes (create from template, rename, restore, deleted list), vaults membership (into `app.vaults`), users and tokens (into `app.auth`). Routers keep parsing, auth dependencies, ETag/If-Match, idempotency replay, problem mapping and schema mapping. | V1 | Largest item; existing API and contract tests are the safety net, no OpenAPI change expected. |
| A7 | Table ownership: amend ADR-0003 with an owner per table and the allowed cross-module reads; route the remaining cross-module writes through the owner. Break the notes and tasks cycle by moving index orchestration (which calls both notes and tasks extractors) out of `notes.index` into a small `app/sync/index.py` step that depends on both. | V6, V7 (notes and tasks) | No repository layer per table; only the writes move. |
| A8 | Bring the documents in line with the code: ADR-0003 (synchronous post-commit indexing, rebuild repairs it; AI runs in the worker, no `ai` process), ADR-0013 (SSE instead of WebSocket), `app/ai/jobs.py` docstring after A1. | V8 | Decision for Flemming: keep synchronous indexing (search sees a note at once, simpler) and fix the ADR, or move indexing to the worker as the ADR says. Recommended: keep it and fix the ADR. |

Suggested order: A0, A1, A2, A3, A5, A4, A6 (several PRs), A7, A8. A1 is the only one that
changes behaviour users can see and is worth doing first on its own.
