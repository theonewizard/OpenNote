# Testing Strategy

Status: Proposed (2026-10-17). Implements design §15.13 and `CLAUDE.md` §9. Storage and sync carry the data-integrity risk, so they get the deepest testing; UI layers get enough to catch regressions.

## 1. Principles

- Tests assert behaviour users depend on (bytes on disk, revisions, conflicts), not implementation details. No coverage-chasing (design §15.13).
- Never mock the thing under test. Storage tests use real temporary directories; backend integration tests use real PostgreSQL and Valkey (CI service containers / Compose), never SQLite stand-ins for PostgreSQL behaviour.
- Every bug fix gets a regression test that fails before the fix (`CLAUDE.md` §9).
- Failing tests are never skipped, deleted or weakened to get green (`CLAUDE.md` §9, design §15.6).
- Randomized tests are seeded; a failing seed is printed and becomes a fixed regression case.

## 2. Test layers

| Layer | Location | Tools | Runs |
|---|---|---|---|
| Backend unit | `backend/tests/unit` | pytest, Hypothesis | Every push |
| Backend integration | `backend/tests/integration` | pytest + real PostgreSQL/pgvector + Valkey + temp vault dirs; Alembic upgrade from empty and downgrade one step | Every push |
| API contract | `tests/integration/contract` | Schemathesis against the running API and committed `docs/api/openapi.json` (Phase 2+); OpenAPI drift check (`make openapi`, then `git diff --exit-code` on the generated files; `docs/api/openapi.json` is generated and committed from Phase 0) | Every push (drift check: CI added in Phase 0 Task 9; Schemathesis: Phase 2+) |
| Compatibility | `tests/compatibility` | Shared corpus, run by Python and Swift parsers | Every push (Phase 1+) |
| Sync simulation | `backend/tests/sync_sim` | Seeded simulation, invariants I1–I6 of the sync protocol | 500 seeds per push; 10,000 nightly |
| Web unit/component | `web/tests/unit` | Vitest, Testing Library | Every push |
| Web end-to-end | `tests/e2e/web` | Playwright (Chromium, WebKit) against Compose stack | Every push to PR (Phase 3+) |
| Apple packages | `apple/Packages/*/Tests` | Swift Testing / XCTest; Core and Storage also on Linux | Every push (macOS runner) |
| Apple UI | `apple/Tests` | XCUITest on simulators (iPhone, iPad, Mac) | PRs touching `apple/` (Phase 4+) |
| Cross-client sync | `tests/e2e/sync` | Backend + headless Swift sync engine (`swift run opennote-sync-cli`) + Playwright web client editing one vault | Nightly (Phase 5+) |
| Performance | `tests/performance` | Generated 100k-note vault; pytest-benchmark for backend, k6 for API; Swift `measure` for local save/open | Nightly, compared against baseline |
| Security | CI jobs | ruff security rules + bandit, pip-audit, npm audit, Trivy (images and filesystem), gitleaks, Semgrep; path-traversal and upload fuzz tests in integration suite | Every push; images weekly |
| Container | CI job | Build all images, start Compose, wait for health, run smoke tests, run as random UID (`--user 1000870000:0`) with read-only root FS | Every push to PR |

## 3. Compatibility corpus

`tests/compatibility/vaults/` holds small hand-made vaults; each case is one file plus an `expected.json` listing extracted links, tags, embeds, frontmatter properties and errors.

Required cases (Phase 1, P1-10):

- Frontmatter: none; empty; lists vs strings; comments; anchors/aliases; multi-document; `...` terminator; invalid YAML; BOM before `---`; CRLF; Windows-1252 file.
- Links: every wiki-link form, embeds with size, block refs, Markdown links with spaces/encoding/angle brackets, links in code (must not extract), unresolved, ambiguous names in different folders.
- Tags: inline, nested, in headings, in code, in URLs (`#fragment`), unicode tags, numeric-only (`#123` is not a tag in Obsidian).
- Syntax preservation: callouts (nested, foldable), Mermaid, math, footnotes, HTML, Dataview queries, Templater syntax, `%%comments%%`, tables with alignment, tabs vs spaces, trailing whitespace, no trailing newline, very long lines, 10 MB note.
- Paths: NFD names, case-fold collisions, reserved names, `#`/`^` in names, deep nesting, 255-byte names.
- Obsidian-specific files: `.obsidian/` contents, `.canvas`, `.base`, `.trash/`.

Invariants per case: byte-identical round trip; metadata edits change only the targeted YAML node; extraction equals `expected.json` in both Python and Swift.

A property-based test (Hypothesis) generates Markdown from a grammar of the above constructs and checks the same invariants. Real-world vaults are never committed; developers can point `OPENNOTE_COMPAT_VAULT` at a private vault for a local read-only run.

## 4. Sync simulation

Implemented with the P1-12 prototype and kept for the life of the project.

- Actors: server, 2–5 clients, an "external editor" writing directly to a client vault or the server vault.
- Actions: create/edit/move/delete notes and attachments, go offline/online, push, pull, crash between any two steps, duplicate or reorder requests, expire cursors.
- Checks after each run: invariants I1–I6; every conflict copy's content equals one side's content; history contains every committed revision.
- Shrinking: Hypothesis stateful testing (`RuleBasedStateMachine`) gives minimal failing sequences.

## 5. CI gates (required to merge)

1. Lint and format: ruff, eslint, prettier, swift-format.
2. Type check: mypy `--strict`, `tsc --noEmit`, Swift 6 strict concurrency.
3. Unit + integration + compatibility + 500-seed simulation.
4. Web build; Apple packages `swift build` + `swift test` on macOS; generated Xcode project builds for macOS and iOS Simulator (Phase 0 onward).
5. Container build + Compose smoke test.
6. Security scans with no critical/high findings without a recorded exception.
7. OpenAPI drift check.

## 6. Reference hardware for performance targets

Design §15.14 targets are measured on: MacBook Air M2 16 GB (macOS client), iPhone 15 (iOS client), and a 4 vCPU / 8 GB Linux VM with SSD storage (server). Results are recorded in `docs/development/benchmarks.md` per release; targets are validated, not assumed.
