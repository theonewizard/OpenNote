# Apple Phase 4 completion plan (P4-03, P4-05 to P4-08)

Date: 2026-11-22. Branch `feature/apple-phase-4`, worktree `.worktrees/apple/`. Design: [2026-11-22-apple-apps-phase-4-design.md](../specs/2026-11-22-apple-apps-phase-4-design.md). Record: [.conversations/2026-11-22-apple-phase-4.md](../../../.conversations/2026-11-22-apple-phase-4.md).

## Starting point

`main` (1baa1ea): the five packages build and test (`swift test`: Core 14, Storage 20, API 3, Sync 21, Editor 8 tests, run locally on Xcode 27.2); both app targets are the Phase 0 placeholder. `OpenNoteAPI` has the generated client and nothing else. The server side of login exists since Phase 2 (`backend/app/api/auth.py`: client `opennote-apple`, redirect `opennote://auth/callback`) and the web login page follows `/login?auth_request=` since #95. No backend change, so `docs/api/openapi.json` stays as it is.

## Rulings

- R-P4-001: "Complete Phase 4" means every Phase 4 row that is not COMPLETED: P4-03, P4-05, P4-06, P4-07 and P4-08 (P1 included), as "finish up phase 3" did for Phase 3.
- R-P4-002: The app is local-first over the vault folder through the stateless `Vault`; the engine syncs the same folder beside it (design, approach 1). The app never opens the engine's state database.
- R-P4-003: A vault can be used with no account. That is what makes the apps usable offline from the first launch and lets the UI tests run with no server.
- R-P4-004: Login is the server's authorization code flow with PKCE in `ASWebAuthenticationSession`, with the shared browser session (a web session in Safari signs the app in without typing). The server address must be `https`, or `http` on a loopback host for development.
- R-P4-005: Credentials are one Keychain generic-password item per server, readable after first unlock, this device only. Nothing else stores a token.
- R-P4-006: swift-openapi-urlsession 1.4.0 is added to `OpenNoteAPI`, pinned exactly. Rejected: a hand-written `ClientTransport` over `URLSession`, because the engine needs streamed responses (`GET /events`, blob downloads) and that is what the package implements.
- R-P4-007: `SyncEngine` gains one thing: a callback after each round. The app reloads its list from it and shows the error, if any.
- R-P4-008: macOS stores the chosen folder as a path in `UserDefaults`; iOS stores a folder name under Documents. A launch argument (`-vaultFolder`) overrides it like any default, which is how the UI tests get a fresh vault.
- R-P4-009: Name rules the app needs for new files (`sanitizedName`, `freePath`) live in `OpenNoteCore.VaultPath` with tests, not in the app targets.
- R-P4-010: The share extension writes to an App Group inbox and the app imports it; quick capture is an App Intent plus `opennote://capture?text=`; notifications are local, for newly flagged files only. Reminder notifications stay with P6-02.
- R-P4-011: UI tests are one set of XCUITest sources built for both platforms (`apple/Tests/OpenNoteUITests`). `SmokeTests`: create, edit, find and reopen a note; quick capture by URL; three panes on iPad. They run in the `apple` workflow on the Mac, an iPhone simulator and an iPad simulator. `LiveServerTests` (iOS) signs in to a running server and syncs both ways; it is skipped unless a server is named, and is run by hand.
- R-P4-012: The project is signed ad hoc, not unsigned: the simulator registers the iOS App Group only for a signed build.

## Tasks

1. `OpenNoteCore`: `VaultPath.sanitizedName` and `freePath` with tests.
2. `OpenNoteAPI`: `ServerAddress`, `PKCE`, `OAuthClient`, `KeychainStore`, `Session`, `BearerAuth`, the URLSession transport; tests against a stub transport (P4-03).
3. `OpenNoteSync`: the round callback; `OpenNoteEditor`: files dropped on the macOS text view.
4. App: `AppModel`, `NoteWindow`, welcome, three panes, editor with save and reload, note actions, search, attachments, account view, commands (P4-05, P4-06, P4-07).
5. iOS: Files exposure, camera; share extension, App Group inbox, capture intent and URL, notifications (P4-06, P4-08).
6. UI tests and the workflow steps (R-P4-011).
7. Runtime check: a local server (PostgreSQL, Valkey, uvicorn, the web app for the login page), sign in from the Mac app and the iPhone simulator, edit on one and see it on the other.
8. Docs (setup, versions, testing strategy, user guide, threat model), ROADMAP and IMPLEMENTATION_STATUS, conversation record, review, commit.
