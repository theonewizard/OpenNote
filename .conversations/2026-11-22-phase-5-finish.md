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

## Output

- Phase 5 web UI pull request: `web/src/features/ConflictView.tsx`, `HistoryView.tsx`, `DiffView.tsx`, `web/src/lib/diff.ts`, navigation and note toolbar wiring, mock conflict/revision/content routes, tests (`diff.test.ts`, `sync-ui.test.tsx`, e2e `sync-ui.spec.ts`). Verified: vitest 8 files / 91 tests, Playwright 19 tests, lint, typecheck, build; one scripted run against a local API where an offline browser edit and a direct `PUT` from "another device" on the same line produced a real conflict copy, which was resolved with Use copy in note, then revision 1 restored from History.
