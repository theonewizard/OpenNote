# OpenNote Architecture Specification

| | |
|---|---|
| Status | Proposed, awaiting review |
| Date | 2026-10-17 |
| Source | "Consulting OpenNotes — Powered by Obsidian" design document (sections 1–18), in particular section 15 "Master Development Instructions" |
| Covers | Section 15 §20 steps 1–9: requirements analysis, risks, architecture, roadmap, repository structure, ADRs, API and storage contracts, sync protocol, testing strategy |

This specification turns the design document into decisions an engineer can build against. It does not repeat the design document; it records what the document leaves open, where it contradicts itself, and how each gap is resolved. Detailed contracts live in their own files and are linked from here.

| Companion document | Purpose |
|---|---|
| [Storage contract](../../architecture/storage-contract.md) | Vault layout, file rules, parsing and write rules |
| [API contract](../../api/api-contract.md) | REST/WebSocket conventions, resources, endpoints, search grammar |
| [Sync protocol](../../architecture/sync-protocol.md) | Revisions, change feed, push, merge, conflicts, tombstones |
| [Testing strategy](../../development/testing-strategy.md) | Test layers, corpora, CI gates |
| [Threat model](../../security/threat-model.md) | Assets, trust boundaries, threats, controls |
| [ADRs](../../architecture/adr/README.md) | One record per decision |
| [Roadmap](../../ROADMAP.md) | Work items with dependencies and acceptance criteria |
| [Phase 0 plan](../plans/2026-10-17-phase-0-foundation-plan.md) | Task-level plan for the foundation |

---

## 1. Requirements analysis

### 1.1 What the product is

A self-hosted, local-first note platform whose authoritative data is an Obsidian-compatible Markdown vault, with native SwiftUI clients (macOS, iOS, iPadOS), a React web client, a Python/FastAPI backend in UBI containers, and optional local AI. The defining success test (design §17) is narrow: **safely store, edit and synchronize an existing Obsidian vault across macOS, iOS and web.** Everything else is incremental.

### 1.2 Requirement classes

| Class | Requirements that drive architecture | Source |
|---|---|---|
| Data ownership | Markdown files are authoritative; DB is derived and rebuildable; no proprietary conversion; never silently rewrite unsupported syntax | §3.1, §15.2.2–2.3 |
| Local-first | Native apps fully usable offline; local save < 100 ms; no content loss on network failure | §1.2, §15.2.1, §15.14 |
| Sync correctness | Revision preconditions on every mutation; never silently overwrite; preserve both sides on unsafe merge; tombstones; resumable; loop-free; timestamps never authoritative | §7, §15.9 |
| Obsidian coexistence | Detect external edits; do not add metadata on open; keep `.obsidian/` untouched; app data outside the vault | §3, §4, §16.B |
| Self-hosting | UBI images; Compose, Podman, Kubernetes, OpenShift (arbitrary UID, restricted SCC); no privileged containers | §11, §15.2.4 |
| Security | OIDC + local auth, vault-level ACL, path traversal protection, audit log, rate limits, scanning, no E2E claims | §12, §15.15 |
| Performance | 100k-note vaults; search < 500 ms; cached open < 200 ms; non-blocking indexing; incremental sync | §15.14 |
| Optional AI | Disabled by default; local first; provider abstraction; cited answers; prompt-injection resistance; never modifies notes without approval | §9, §15.12 |

### 1.3 Scope boundary for v1 (MVP, design §17)

In: Markdown notes, folders, tags, attachments, full-text search, macOS/iOS/iPadOS/web, offline editing, sync, Obsidian compatibility, basic version history.
Out until after MVP: tasks, calendar, web clipping, AI, collaboration, sharing, email-to-note, CRDT editing, client-side encryption.

### 1.4 Approach to "reverse engineering Evernote v11"

Design §1.4 asks for the experience to be based on reverse-engineering Evernote v11. This plan derives feature parity **only from Evernote's published product information, documentation and observable UI behaviour**. It does not decompile Evernote clients, reuse Evernote assets or trademarks, or implement Evernote's private protocols. That keeps the project clear of licence and terms-of-service exposure while still matching the feature inventory in design §2.1. An optional ENEX importer (Evernote's documented export format) is a reasonable later roadmap item.

---

## 2. Contradictions in the design document and how they are resolved

Where sections disagree, section 15 (written as instructions) wins unless there is a data-integrity reason not to; each resolution is an ADR.

| # | Conflict | Resolution | ADR |
|---|---|---|---|
| C1 | §6.1 "deploy a collection of independent microservices" vs §15.2.7 and §16 "modular monolith" | Modular monolith; worker and AI run as separate processes from the same codebase | [ADR-0003](../../architecture/adr/0003-modular-monolith-backend.md) |
| C2 | §15.7 phase order API → web → Apple → sync vs §18 storage → **sync prototype** → API → clients | Keep §15 order, add a time-boxed **sync protocol prototype** (server-side, test harness only) at the end of Phase 1 so the protocol is proven before the API freezes | [ADR-0004](../../architecture/adr/0004-phase-order-and-early-sync-prototype.md) |
| C3 | §4 example writes `modified:` in frontmatter vs §15.8 "no device-specific state in Markdown" and churn against Obsidian | OpenNote never auto-updates `modified`/`created`; preserves them if present; timestamps come from revisions | [ADR-0006](../../architecture/adr/0006-note-identity.md) |
| C4 | §6.3 TipTap/ProseMirror vs §6.3 "Markdown-first editor with live preview" and §10 "preserve unsupported syntax" | Web uses CodeMirror 6 (source-preserving) for v1; WYSIWYG revisited only after the round-trip corpus exists | [ADR-0008](../../architecture/adr/0008-markdown-first-editor.md) |
| C5 | §6.1 says notes API is `/api/v1/notes` (flat) while vaults are the access-control unit | Keep the flat paths from §13 Phase 2; `vault_id` is a required attribute/filter; authorization is always resolved through the note's vault | [API contract](../../api/api-contract.md) |
| C6 | §15.3 "Redis-backed background jobs" vs Redis's 2024+ licence change | Use the Redis protocol; ship **Valkey** (BSD) as the default server, any Redis-compatible server works | [ADR-0009](../../architecture/adr/0009-background-jobs.md) |
| C7 | §11 "UBI where practical" vs no freely pullable UBI images for PostgreSQL+pgvector and Valkey | Build our own UBI-based images for those two; dev Compose may use upstream images via an override file | [ADR-0010](../../architecture/adr/0010-container-images.md) |
| C8 | §6.2 shows a checked-in `OpenNote.xcodeproj` | Generate it from `project.yml` with XcodeGen; generated project is not committed | [ADR-0011](../../architecture/adr/0011-apple-project-generation.md) |
| C9 | §15.6 worktree path `.worktrees///` is truncated | Follow `CLAUDE.md` §6: worktrees under `.worktrees/<subsystem>/`, branches `feature/…`, `fix/…`, `security/…`; `.worktrees/` is git-ignored | [Development workflow](../../development/workflow.md) |
| C10 | §15.6 spec/plan filenames `YYYY-MM-DD--design.md` miss the topic slug | Use `YYYY-MM-DD-<topic>-design.md` and `YYYY-MM-DD-<topic>-plan.md` | this file |

---

## 3. Architectural risks

Ranked by likelihood × impact on user data. Each has an owner work item in the [roadmap](../../ROADMAP.md).

| # | Risk | Impact | Mitigation | Roadmap |
|---|---|---|---|---|
| R1 | Markdown round-trip corruption by editors or metadata writes | Silent data loss in user vaults | Byte-preserving model: edits are text patches, never re-serialization; frontmatter edited with a comment/order-preserving YAML library; property-based round-trip tests over a compatibility corpus before any editor ships | P1-02, P1-03, P1-10 |
| R2 | Sync divergence or lost updates (offline edits, interrupted pushes, retries) | Lost or duplicated content | Server-assigned per-file revisions and a per-vault change sequence; idempotent client operation IDs; server-side three-way merge with history as merge base; conflict copies; deterministic multi-client simulation tests with fault injection; sync prototype in Phase 1 | P1-12, P5-* |
| R3 | Concurrent writers to the same files (Obsidian, OpenNote app, server, third-party sync such as iCloud) | Torn writes, phantom conflicts, sync loops | Atomic temp-file + rename writes; watcher debounce and hash comparison against last-known synced hash; documented "one sync engine per vault" rule with detection of `.obsidian/plugins/obsidian-sync`/iCloud paths and a warning | P1-07, P5-08 |
| R4 | Filesystem semantic differences: APFS case-insensitive and NFD names vs Linux case-sensitive; characters illegal on iOS/Windows/Obsidian links | Two notes collapse into one on Mac; files unsyncable | All paths NFC-normalized for comparison; server rejects case-fold collisions within a folder; filename validator shared by all clients via the API | P1-04 |
| R5 | Note identity for files without `id` (existing Obsidian vaults) across renames | History and links break on rename | Server-side identity registry: `id` frontmatter when present, otherwise server-assigned file ID tracked through rename detection (move op from clients, content-hash matching for external renames) | P1-05 |
| R6 | 100k-note vault scale: initial index, watcher limits (inotify), first sync volume | Slow start, missed events | Batched streaming indexer; periodic full reconciliation scan as safety net for missed watcher events; content-addressed blob transfer; `fs.inotify.max_user_watches` documented for hosts | P1-08, P8-01 |
| R7 | iOS sandbox: user-chosen vault folders, background execution limits, File Provider complexity | Offline vault not directly openable by Obsidian on iOS | v1 stores the iOS vault in the app's own container, exposed through the Files app; File Provider deferred; Obsidian-on-iOS interop documented as a limitation | P4-06 |
| R8 | Web offline: browser cannot hold a real vault | False expectation of parity | Web uses IndexedDB cache plus the same sync protocol; documented as cache, not vault | P3-08 |
| R9 | Auth complexity across native, web and OIDC providers | Insecure token handling or lock-out | Server is its own token issuer (OAuth 2.0 authorization code + PKCE for every client); upstream OIDC or local password as login methods; Keychain/IndexedDB-free token storage on web (httpOnly cookie) | P2-02 |
| R10 | Licence and image supply chain (Redis licence, Red Hat registry auth, PGDG/pgvector RPMs) | Unbuildable or unlicensable images | ADR-0009, ADR-0010; image build in CI from `registry.access.redhat.com` (no auth) plus PGDG repository | P0-07 |
| R11 | AI prompt injection from note content; data exfiltration to external providers | Privacy breach, unwanted edits | AI off by default, local providers only unless explicitly configured per vault; retrieved text wrapped as data; AI writes only through user-approved suggestions | P7-* |
| R12 | Scope: nine phases for a small team | Nothing reaches "reliable" | MVP gate after Phase 5; Phases 6–7 do not start until M5 acceptance passes | roadmap |

---

## 4. Unresolved decisions (need Flemming)

D1, D7 and D8 were decided by Flemming on 2026-10-17. The others are not blocking Phase 0; each has a default the plan uses until told otherwise.

| # | Decision | Default used in this plan |
|---|---|---|
| D1 | Project licence | **Decided: AGPL-3.0** (Flemming, 2026-10-17). Anyone who runs a modified OpenNote as a network service must offer its source to users. `LICENSE` holds the full text |
| D2 | Tenancy in v1: single owner per server vs multi-user with per-vault ACL | Multi-user with owner/editor/viewer roles in the data model from day one; UI exposes owner only until Phase P2 sharing |
| D3 | Minimum Apple OS versions | macOS 15, iOS/iPadOS 18 (SwiftUI and TextKit 2 maturity; Swift 6 strict concurrency) |
| D4 | Minimum OpenShift/Kubernetes versions | OpenShift 4.16+, Kubernetes 1.30+ |
| D5 | Whether OpenNote may write an `id` into existing notes when the user edits (not opens) them | No. IDs are written only to notes OpenNote creates, or by an explicit per-vault "normalize" action |
| D6 | Version-history retention default | Keep all revisions 30 days, then daily snapshots for 1 year; configurable per vault |
| D7 | Whether `CLAUDE.md` §11–§14 (TrueNAS host, `get_api_key`, Zod `/api` proxy) apply to OpenNote as written | **Decided: adapt** (Flemming, 2026-10-17). §11 now names OpenNote production hosts, §12 the OpenNote dependencies and path, §14 the generated-client contract; the secret rules are unchanged |
| D8 | Rename `claude.md` to `CLAUDE.md` so Claude Code loads it on case-sensitive systems | **Decided: renamed** in this PR (Flemming, 2026-10-17) |

---

## 5. System architecture

### 5.1 Component view

```
 Clients                                   Server (one codebase, three process types)
 ┌──────────────────────┐                  ┌───────────────────────────────────────────┐
 │ macOS / iOS / iPadOS │  HTTPS (REST)    │ opennote-api (FastAPI, uvicorn)           │
 │  SwiftUI app         │ ───────────────▶ │  modules: auth, vaults, notes,            │
 │  OpenNoteSync engine │  WSS (events)    │  attachments, search, sync, (tasks, ai)   │
 │  local vault (files) │ ◀─────────────── │                                           │
 │  SQLite state + base │                  │ opennote-worker (same image)              │
 ├──────────────────────┤                  │  indexing, history GC, watcher reconcile, │
 │ Web (React PWA)      │                  │  OCR/AI job dispatch                       │
 │  IndexedDB cache     │                  │                                           │
 │  same sync protocol  │                  │ opennote-ai (optional, separate image)    │
 └──────────────────────┘                  └───────┬───────────────┬───────────────┬───┘
                                                   │               │               │
                                    vault volume ◀─┘   PostgreSQL ◀┘   Valkey ◀────┘
                                    (Markdown, attachments)  (index, revisions, auth,  (job queue,
                                    history volume           sync log, pgvector)        pub/sub)
                                    (content-addressed revisions)
```

### 5.2 Source of truth and derived data

| Data | Authoritative store | Derived / rebuildable from |
|---|---|---|
| Note content, attachments | Vault files on the server vault volume (and each native client's local vault copy) | — |
| Revision history content | History object store on a separate volume (content-addressed, outside the vault) | — (backed up with the vault) |
| Revision metadata, change sequence | PostgreSQL | History store + vault scan (rebuild procedure in P8) |
| Users, devices, ACLs, sessions | PostgreSQL | — (backed up) |
| Search index, tags, links, embeddings | PostgreSQL | Vault scan |
| Client sync state, merge bases | Client SQLite / IndexedDB, outside the vault | Re-sync from server |

### 5.3 Backend module boundaries

Python package `opennote` under `backend/app/` (import name `app` per §15.4). Each module owns its tables and exposes a service interface; other modules call the service, never the tables.

| Module | Owns | Depends on |
|---|---|---|
| `vaults` | Vault registry, `.opennote/config.json`, path rules, atomic file I/O, watcher | — |
| `notes` | Note parsing (frontmatter, links, tags), note identity registry | `vaults` |
| `attachments` | Blob store, attachment registry, upload validation | `vaults` |
| `sync` | Revisions, change log, push/pull, merge, conflicts, tombstones, history store | `vaults`, `notes`, `attachments` |
| `search` | Full-text index, query parser, (later) hybrid search | `notes` |
| `auth` | Users, identities, OAuth/OIDC, tokens, devices, ACL checks | — |
| `api` | HTTP/WebSocket routers, schemas, error mapping | all services |
| `workers` | Job definitions and scheduling | services |
| `tasks`, `calendar`, `ai` | Later phases | `notes`, `search` |

All note mutations, from any client or from the watcher, go through `sync`. That single write path is what makes revisions trustworthy.

### 5.4 Native client architecture

Swift packages (one repository, local SPM packages):

| Package | Responsibility | Platform deps |
|---|---|---|
| `OpenNoteCore` | Domain types, Markdown/frontmatter scanning (byte-preserving), link/tag extraction, path rules | Foundation only (Linux-buildable) |
| `OpenNoteStorage` | Local vault file I/O (atomic writes, coordinated access), SQLite state DB, base-content cache | Foundation, SQLite (Linux-buildable) |
| `OpenNoteAPI` | Generated client from OpenAPI (swift-openapi-generator), auth/session | Foundation, URLSession |
| `OpenNoteSync` | Outbox, pull/push loop, watcher integration (FSEvents/`NSFilePresenter`), conflict surfacing | Core, Storage, API |
| `OpenNoteEditor` | TextKit 2 Markdown editor with live styling, no re-serialization | SwiftUI/AppKit/UIKit |

The apps (`Apps/macOS`, `Apps/iOS`) are thin SwiftUI shells over these packages. macOS keeps the local vault in a user-chosen folder (so Obsidian can open it); iOS keeps it in the app container (R7).

### 5.5 Web client architecture

React + TypeScript + Vite, Tailwind + shadcn/ui, TanStack Query for server state, Zustand for UI state, CodeMirror 6 editor with Markdown live preview decorations, IndexedDB (via `idb`) for offline cache and outbox, service worker for app-shell caching. Typed API client generated with `openapi-typescript` from the backend's OpenAPI document. Web runs the same push/pull protocol as native clients but holds a cache, not a vault. The IndexedDB cache is namespaced per user and vault and cleared on logout or account switch without silently discarding unsynced edits ([ADR-0015](../../architecture/adr/0015-web-offline-cache.md)).

### 5.6 Data flow: one edit, end to end

1. User types in the macOS editor. `OpenNoteEditor` emits text; `OpenNoteStorage` writes the file atomically (< 100 ms target) and records `local_hash`.
2. `OpenNoteSync` appends an `update` operation (client_op_id, file_id, base_revision, new content hash) to the durable outbox.
3. When online, the client uploads the blob if the server lacks that hash, then pushes the operation.
4. Server `sync` checks `base_revision` against current: equal → commit revision n+1; behind → three-way merge with history base; clean → commit merged revision and return it; unclean → commit server side as current, store the client's version as a conflict copy, return `conflict`.
5. Commit follows the [commit procedure](../../architecture/sync-protocol.md#23-commit-procedure): history object, PostgreSQL revision and change sequence, history log, then the vault file. Search and link indexes update asynchronously via the worker, so search is eventually consistent; the note itself is readable immediately. A change event is published.
6. Other clients receive the event over WebSocket (or poll) and pull changes since their cursor.

Details: [sync protocol](../../architecture/sync-protocol.md).

---

## 6. Repository structure

Monorepo as in §15.4, with these concrete additions:

```
OpenNote/
├── CLAUDE.md                 # agent working rules (see §11)
├── .conversations/           # every prompt, per CLAUDE.md "Document every prompt"
├── README.md
├── LICENSE                   # AGPL-3.0 (D1)
├── Makefile                  # single entry point: make bootstrap|lint|test|build|up
├── .github/workflows/        # backend, web, apple, containers, security
├── .editorconfig  .gitignore  .pre-commit-config.yaml
├── backend/
│   ├── pyproject.toml        # project metadata, ruff, mypy, pytest config
│   ├── requirements.txt      # pinned runtime deps (CLAUDE.md §3)
│   ├── requirements-dev.txt  # pinned test/lint tools, includes requirements.txt
│   ├── alembic.ini
│   ├── app/                  # modules listed in §5.3, plus core/ (config, logging, db, telemetry)
│   │   └── api/main.py       # app factory + assert_routes_authenticated / KEYLESS_ROUTES (CLAUDE.md §12)
│   ├── migrations/
│   └── tests/{unit,integration}/
├── web/
│   ├── package.json  package-lock.json  vite.config.ts  tsconfig.json
│   ├── src/{app,components,features,lib,api}/
│   ├── public/
│   └── tests/{unit,e2e}/
├── apple/
│   ├── project.yml           # XcodeGen spec (ADR-0011)
│   ├── Apps/{macOS,iOS}/
│   ├── Packages/{OpenNoteCore,OpenNoteAPI,OpenNoteStorage,OpenNoteSync,OpenNoteEditor}/
│   └── Tests/                # app-level UI tests
├── infrastructure/
│   ├── containers/{api,web,postgres,valkey}/Containerfile
│   ├── compose/{compose.yaml,compose.dev.yaml,.env.example}
│   ├── kubernetes/           # kustomize base
│   ├── helm/opennote/
│   └── openshift/            # Route, SCC notes, kustomize overlay
├── docs/                     # as §15.4, plus architecture/adr/
├── scripts/                  # bootstrap.sh, gen-openapi.sh, gen-clients.sh
└── tests/{integration,e2e,compatibility,performance}/
    └── compatibility/vaults/ # Markdown corpus (see testing strategy)
```

---

## 7. Contracts (summaries)

### 7.1 Storage contract

Full text: [storage-contract.md](../../architecture/storage-contract.md). Key rules:

- A vault is a directory. `*.md` files are notes; every other non-ignored file is an attachment. `.obsidian/` is preserved and never written. `.opennote/` holds only `config.json` (vault UUID, schema version, portable settings).
- Bytes are sacred: encoding, BOM, line endings, trailing newline and unknown syntax are preserved; OpenNote edits are text replacements, never parse-and-re-render.
- Frontmatter edits (tags, aliases, `opennote:` namespace) use a round-tripping YAML editor; if the frontmatter cannot be parsed, the note is still readable and editable as text but metadata edits are refused.
- Identity: frontmatter `id` (UUIDv7) when present; otherwise a server-assigned file ID; never inserted on open.
- Writes are atomic (temp file in the same directory, fsync, rename, fsync directory).
- Paths are vault-relative, NFC-normalized, `/`-separated, validated against traversal and a shared filename rule set.

### 7.2 API contract

Full text: [api-contract.md](../../api/api-contract.md). Key rules: `/api/v1`, JSON, RFC 9457 problem details, UUIDv7 IDs, RFC 3339 UTC times, cursor pagination, `ETag`/`If-Match` revision preconditions (428 when missing, 412 when stale), `Idempotency-Key` on POST, OpenAPI 3.1 generated from code and committed to `docs/api/openapi.json`, typed clients generated for TypeScript and Swift.

### 7.3 Sync protocol

Full text: [sync-protocol.md](../../architecture/sync-protocol.md). Revision-based, server-authoritative, pull-by-cursor plus push-with-base-revision, server-side three-way merge, conflict copies, tombstones, content-addressed blobs, idempotent operations.

---

## 8. Cross-cutting concerns

- **Configuration:** twelve-factor env vars (`OPENNOTE_*`) via `pydantic-settings`; secrets from files (`*_FILE`) for Kubernetes/OpenShift secrets.
- **Observability:** OpenTelemetry traces and metrics (OTLP exporter optional), structured JSON logs with request IDs, `/healthz` (liveness) and `/readyz` (DB, Valkey, vault volume writable).
- **Audit log:** append-only table for auth events, ACL changes, deletes, conflict resolutions, admin actions.
- **Containers:** non-root, arbitrary UID (group 0 writable dirs), read-only root filesystem, no capabilities, `HEALTHCHECK` equivalents via probes.
- **Accessibility and i18n:** UI strings externalized from Phase 3/4; VoiceOver and keyboard navigation verified in Phase 8.

---

## 9. Testing strategy (summary)

Full text: [testing-strategy.md](../../development/testing-strategy.md). The non-negotiable parts:

1. **Compatibility corpus** of Markdown vaults (frontmatter variants, wiki-links, embeds, callouts, block refs, CRLF, BOM, non-UTF-8, unicode names, huge files) with a byte-identity round-trip assertion for every read/write path, in Python and Swift, before any editor ships.
2. **Sync simulation**: deterministic, seeded multi-client simulation with fault injection (drop, duplicate, reorder, crash mid-push) and invariants: no acknowledged edit is ever lost; every divergent edit is either merged or present as a conflict copy; all replicas converge.
3. **Contract tests** against the committed OpenAPI document (Schemathesis) and generated-client compile checks.
4. CI gates on lint, type check, unit, integration (real PostgreSQL + Valkey service containers), security scans; Apple packages built and tested on GitHub's macOS runners.

---

## 10. Implementation order

Phases follow §15.7, with the sync prototype added to Phase 1 (ADR-0004) and an explicit MVP gate:

| Phase | Outcome | Gate to next |
|---|---|---|
| 0 Foundation | Repo, CI, containers, skeleton apps | M0: everything builds; backend starts in containers; CI green |
| 1 Storage + sync prototype | Byte-preserving vault engine; protocol proven in simulation | M1: corpus round-trips; simulation invariants hold |
| 2 Backend API | Auth, vault/note/attachment/tag/search endpoints with preconditions | M2: contract tests green |
| 3 Web | Three-pane app, editor, search, offline cache | M3 |
| 4 Apple | macOS, iOS, iPadOS apps with local vault | M4 |
| 5 Sync | Full protocol in all clients, history, conflict UI | **M5 = MVP**: §15.17 items 1–9 hold |
| 6 Productivity, 7 AI, 8 Hardening | As design | M6–M8 |

Work items, dependencies and acceptance criteria: [ROADMAP.md](../../ROADMAP.md).

---

## 11. Alignment with `CLAUDE.md`

The repository's `CLAUDE.md` (added 2026-10-17) governs how work is done. This plan follows it; points where it shapes the architecture:

| `CLAUDE.md` rule | Effect on this plan |
|---|---|
| §1.8 latest stable versions | The stack in design §6 is a floor. Phase 0 Task 1 resolves and pins the current stable release of each tool (Python, FastAPI, PostgreSQL, Node, React, Swift/Xcode, UBI) and records them in `docs/development/versions.md`; the container base must offer that Python version, otherwise the newest UBI-available one is used and the gap is recorded |
| §3 `.venv` + `requirements.txt` + pip | No uv/Poetry. Pinned `requirements.txt` and `requirements-dev.txt` ([ADR-0014](../../architecture/adr/0014-python-tooling.md)) |
| §6 worktrees and branch names | `.worktrees/<subsystem>/`, `feature/…`; squash-merge to `main` |
| §12 deny-by-default auth | `backend/app/api/main.py` runs `assert_routes_authenticated()` at startup; only paths in `KEYLESS_ROUTES` (`/healthz`, `/readyz`, `/api/v1/meta`, OAuth/OIDC callback and token endpoints) may lack the auth dependency. The dependency is the stricter OAuth bearer check `get_current_principal` (allowed by §12 as "stricter authorization"); a `get_api_key` dependency exists for automation tokens (design §10.5) |
| §13 RFC 9457 errors | Already the API contract's error model; generic `detail`, details logged server-side only |
| §14 frontend API contract | No server-side proxy in v1 (nginx forwards `/api` unchanged). The contract guard is the TypeScript client generated from the committed OpenAPI document plus Zod validation of query parameters in `web/src/api/`; a backend change without regenerating clients fails CI. §14 was rewritten to say this (D7) |
| §23 avoid over-engineering, §28 ponytail audit | Every implementation PR runs the `ponytail-audit` review step; the plan keeps one backend process image, no plugin system, no speculative abstractions beyond the AI provider interface the design requires |
| "Document every prompt" | Prompts are recorded under `.conversations/YYYY-MM-DD-<topic>.md`; the full design document is kept at `docs/design/2026-10-17-opennote-design-document.md` |

**File name.** The file was renamed from `claude.md` to `CLAUDE.md` (D8) so Claude Code loads it automatically on case-sensitive filesystems (Linux containers, CI).

**Carried-over sections.** §11 (TrueNAS `.env`), §12 (`api/main.py`, `get_api_key` only) and §14 (Zod proxy) were inherited from another project. Per D7 they were adapted to OpenNote: §11 treats any host or namespace with real user vaults as production, §12 points at `backend/app/api/main.py` and allows `get_current_principal` or `get_api_key`, §14 describes the generated-client contract above.
