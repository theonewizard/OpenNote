# Web Phase 3 completion plan

Date: 2026-11-21. Thread "Finish Phase 3 web client". Branch `feature/web-phase-3`, worktree `.worktrees/web-phase-3`.

## Starting point

`main` (031f516) has the web shell (P3-02), the CodeMirror editor (P3-04), the PWA shell (P3-10) and the IndexedDB sync engine with offline edits (P3-08, P5-04). The roadmap rows P3-01, P3-03, P3-05, P3-06, P3-07 and P3-09 said TESTING, but the web app had none of them: no login screen, no sort, favorites or archive, no tags, search, attachments or settings, and no way to create, rename or delete a note ("New note" was a disabled button).

All the server endpoints exist (Phase 2 and Phase 6). This plan adds client code only; `docs/api/openapi.json` does not change, so no client regeneration is needed.

## Rulings

- R-P3-001: Create, rename, move, delete, restore, favorite, archive, tag edits, attachment upload and vault settings go through the REST endpoints and need the server. The sync engine pulls the result. Offline the controls stay visible but report the failure; only reading and editing note text work offline (P3-08 acceptance). Before a REST change to a note, the engine syncs that vault so unsynced edits reach the server first.
- R-P3-002: Favorite and archive are `opennote.favorite` and `opennote.archived` in the note's frontmatter (storage contract §2), written with `PATCH /notes/{id}` (`opennote` replaces the namespace, so the client sends the existing keys plus the change). The Favorites and Archive views use `GET /search?q=is:favorite` and `is:archived`. Archived notes are left out of folder, tag and "All notes" lists.
- R-P3-003: Login: the app asks `GET /me`; a 401 shows the login screen, which offers a password form and one button per OIDC provider from `GET /meta` `login_methods`. A network failure with a remembered user opens the offline cache as before. `/login?auth_request=<id>` (native clients without a session) logs in and follows `redirect_to`. Any later 401 returns to the login screen. Sign out posts `/auth/logout`, closes the engine and forgets the remembered user, so a signed-out browser never opens the cache offline.
- R-P3-004: OIDC from the web navigates to `/api/v1/auth/authorize` with `client_id=opennote-web`, `redirect_uri=/`, a random S256 challenge and state, and `provider`; the server's callback sets the session cookie and lands on `/` (no code exchange for the web client).
- R-P3-005: Attachments: uploads go to the open note's folder, named after the file (path separators and control characters replaced); the editor then inserts `![[name]]` at the cursor. In the editor an image embed shows the image under its line (a CodeMirror block widget); other embeds and wiki-links open with Ctrl/Cmd-click. The markup stays visible (styled source, as #36 decided). A folder's attachments are listed under its notes; opening one previews an image in place, or offers to open a PDF in a new tab: the CSP's `frame-ancestors 'none'` forbids framing it.
- R-P3-006: Wiki-link targets resolve with `GET /notes/{id}/links` (`outgoing[].resolved`); embed targets resolve against the vault's attachment list, by path and then by file name, as Obsidian does.
- R-P3-007: Settings is a view in the main pane: account, vaults (create, rename, AI and Obsidian-config switches, delete for owners with the name typed to confirm), members (change role, remove; add from the user list for admins, since only admins can list users), and devices (revoke). Tokens stay API-only for now.
- R-P3-008: Dialogs use `@base-ui/react` Dialog (already a dependency); no new dependencies.

## Tasks

1. API helpers (`sendJson`, 401 handling) and the session gate with the login screen and sign out (P3-01).
2. Note actions: new note, new folder, rename or move (with "update links"), delete, Trash with restore; sort; favorites and archive views and toggles (P3-02, P3-03).
3. Tags in the navigation with counts, tag filter, tag editing on a note (P3-05).
4. Search box with grammar hints and result snippets (P3-06).
5. Attachments: upload, list, preview, embeds in the editor; wiki-link navigation (P3-04, P3-07).
6. Settings and vault management (P3-09).
7. Tests: unit tests with MSW for each task; Playwright for the login flow (P3-01 acceptance) and a create, rename and delete flow; run the existing suites.
8. Runtime check against a local API (PostgreSQL, Valkey, uvicorn, `vite`), then ROADMAP and IMPLEMENTATION_STATUS updates, conversation record, PR.
