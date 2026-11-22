# 2026-11-22 — Finish Phase 5 synchronization

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt").

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 00:05 | Flemming | "Look at phase 5" |

## How the prompt was read

Review Phase 5 on `main` (1baa1ea) against ROADMAP.md and IMPLEMENTATION_STATUS.md, report the real state in the thread, then finish what is open, as "finish up phase 3" was handled. Reported: P5-01, P5-02, P5-07 done; P5-03 and P5-04 merged but never run against each other or (Apple) against the real server; P5-05, P5-06 (client side), P5-08, P5-09 not started; P5-10's web half already on `main` (#95, #84). The Apple halves of P5-05, P5-06, P5-08 and P5-10 need the Apple apps, which are Phase 4 and not built, so this thread does the web halves, the cross-client suite and the server side of P5-08.

## Rulings

- R-P5F-001: diffs are computed in the browser (`web/src/lib/diff.ts`), as the API leaves them to clients (R-P5-007). A line LCS after trimming the common start and end; it gives up above 4,000,000 table cells (about 2,000 changed lines each side) and says so instead of freezing the tab. No diff dependency added (`CLAUDE.md` §20).
- R-P5F-002: resolving a conflict offers Keep note (delete the copy), Use copy in note (`PUT /notes/{id}/content` with the copy's bytes and `If-Match`, then delete the copy) and Keep both (mark resolved only). Each runs inside the layout's `change()`, so unsynced edits on the device are pushed first and a stale revision is a 412 shown to the user, never an overwrite. Deleted copies go to the Trash and every version stays in history.
- R-P5F-003: the conflict list shows paths from the device's sync cache instead of one note request per conflict.
- R-P5F-004: History compares a revision with the revision before it ("changes in this revision") or with the current note (+ marks what restoring brings back). Restore uses `POST /notes/{id}/restore` with the note's current revision as `If-Match`.

- R-P5F-005: the note list, folders, tags, search, attachments, Trash and Conflicts are read again whenever the sync engine reports changed files. Before, a note another device added appeared only after a page reload or a REST change of one's own; found while writing the cross-client suite. Status-only notifications (no file ids) do not refetch.

- R-P5F-006: the cross-client suite's Apple device is `opennote-sync`, an executable target in `OpenNoteSync` that runs one `SyncEngine.sync()` round, because the Apple apps (Phase 4) do not exist yet. It uses the same engine and `OpenAPISyncAPI` as the apps will, over a hand-written URLSession transport (no swift-openapi-urlsession, so no new dependency and no `Package.resolved` change), and signs in as the Apple app does (code + PKCE, client `opennote-apple`, device token).
- R-P5F-007: the suite runs on Linux in the `swift:6.4.1` image, with the backend services as service containers, rather than on the macOS runners: PostgreSQL and Valkey come ready-made there, and the macOS runners are the scarce ones. It runs nightly, on demand, and on pull requests that touch sync code, not on every pull request.
- R-P5F-008: the web app is served by the Vite dev server with its API proxy, the way `npm run dev` runs it, not by nginx; the suite tests sync, and the nginx image is covered by the `containers` workflow.
- R-P5F-009: the scenario steps were checked locally with a throwaway Python stand-in for `opennote-sync` (not committed, as it is not the engine under test); the first run of the real Swift command is in CI.
- R-P5F-011: after #99 (Apple apps) merged, `OpenNoteAPI` no longer built on Linux (CryptoKit for PKCE, Security for the Keychain), which broke the cross-client suite. Fixed by leaving `PKCE` and `KeychainStore` out where those modules do not exist (`#if canImport`) and importing FoundationNetworking for the URLSession transport; no new dependency (swift-crypto for PKCE on Linux was rejected: Linux never starts a login).

## Output

- Phase 5 web UI pull request: `web/src/features/ConflictView.tsx`, `HistoryView.tsx`, `DiffView.tsx`, `web/src/lib/diff.ts`, navigation and note toolbar wiring, mock conflict/revision/content routes, tests (`diff.test.ts`, `sync-ui.test.tsx`, e2e `sync-ui.spec.ts`). Verified: vitest 8 files / 91 tests, Playwright 19 tests, lint, typecheck, build; one scripted run against a local API where an offline browser edit and a direct `PUT` from "another device" on the same line produced a real conflict copy, which was resolved with Use copy in note, then revision 1 restored from History.
- Cross-client pull request: `opennote-sync` (`apple/Packages/OpenNoteSync/Sources/opennote-sync`), `scripts/sync-e2e.sh`, `web/tests/sync-e2e/cross-client.spec.ts`, `web/playwright.sync-e2e.config.ts`, `.github/workflows/sync-e2e.yml`; setup.md §9.
