# 2026-11-22 — Complete Phase 4 (Apple apps)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). One session on Flemming's Mac (macOS 27.2, Xcode 27.2, XcodeGen 2.48.0), branch `feature/apple-phase-4` in `.worktrees/apple`. Design: `docs/superpowers/specs/2026-11-22-apple-apps-phase-4-design.md`; plan and rulings R-P4-001..011: `docs/superpowers/plans/2026-11-22-apple-phase-4-plan.md`.

## Prompts

- Flemming, 2026-11-22: "Build what is need to complete Phase 4." Read as every Phase 4 row not COMPLETED (P4-03, P4-05 to P4-08), as "finish up phase 3" was read (R-P4-001). The design choices in the plan are Claude's, made without asking under `CLAUDE.md` §2, and are Flemming's to overrule.
- Flemming, 2026-11-22, to "say yes and I will push `feature/apple-phase-4` to `origin` and open a draft pull request": "yes". Pushed; pull request #99 (draft). The two fix commits that CI's first run called for were pushed to the same branch under that answer.

## Rulings made while building (beyond the plan)

- The whole Xcode project is signed ad hoc (`CODE_SIGN_IDENTITY: "-"`), no longer unsigned: the simulator registers the iOS App Group only for a signed build (`simctl get_app_container … groups` listed nothing for the unsigned one), and UI test bundles are normally signed this way.
- `Session` takes its signed-out handler at creation, not through a setter, so a refresh can never be rejected before the handler is set.
- The open note asks the file, not the last scan, whether it changed on disk: a scan older than the window's own save would otherwise reload the editor under the cursor.
- Leaving a note whose save was refused because the file changed elsewhere keeps the edits as `… (unsaved edits).md` beside it; only **Reload** drops them. Checked once by hand: a UI test typed into a note while the shell overwrote the file; the file kept the outside text and the copy held the typed text.
- A missing vault folder on the Mac is an error, never recreated: an empty folder in its place would make the engine report every note as deleted.
- Errors from the token call lose their request before they leave `OAuthClient` (a `ClientError` prints its input: the code, the verifier, the refresh token), and the app logs every failed call through `logDescription`.
- Delete has no shortcut: ⌘⌫ in the editor deletes to the start of the line.
- `LiveServerTests` stays in the repository, skipped unless a server is named. It is the only check of the sign-in sheet, and the run that found the timestamp defect.
- `Client(server:transport:middlewares:)` in `OpenNoteAPI` reads the server's timestamps with and without fractional seconds. The sync calls carry no dates and keep the plain initializer.

## What the live run showed

Local server: the API with uvicorn on Python 3.14.10, PostgreSQL 18 with pgvector 0.8.7 and Valkey 9.1.2 from the images the backend workflow uses (Podman), `npm run dev` for the login page on port 5273, a throwaway user and a vault `Test`.

- First attempts failed in the test, not the app: the keyboard covered the page's Sign in button (Return submits instead), and Safari's "Save Password?" sheet held the page until dismissed.
- Then the app signed in (the server listed the device `iPhone 17 Pro`, platform `ios`) and failed to list vaults: `DecodingError … Expected date string to be ISO8601-formatted`. The server writes `created_at` with microseconds; the generated client's default transcoder takes whole seconds only. Fixed with `ServerDates` and a test with both forms.
- After the fix: vault list, the server's note pulled, a note written on the simulator pushed (the server's vault folder held the same bytes), and a note created on the server arrived on the running app in about one second (change hints).
- Sixteen minutes after the sign-in the app was started again: the server's `refresh_tokens` went from two live and none spent to two live and one spent, and a note created on the server still arrived in about a second. The refresh works against the real server.
- A file named `bad:name.md` put into the device's vault was refused by the server; the app then asked for permission to send notifications. The permission sheet could not be answered from outside a UI test, so no delivered notification was seen.

## CI (pull request #99)

- First run (`cdee52c`): backend, web, containers and security green; `apple` failed in the Mac job, in `testCreateEditFindAndReopenANote` only: no editor appeared after "Tap New Note". On macOS `XCUIElement.tap()` is a touch event, which an AppKit toolbar button ignores; the Mac needs `click()`. The Mac build, the signed runner, UI automation on the runner and the Mac quick-capture test all worked in that run.
- Reading that log also showed a race in the app: the search ran once per typed text, so a note saved a moment later (the editor saves 1.5 s after the last key) stayed out of the results. The search now runs again when the vault changes.
- Second run (`b863c52`): all five workflows green (https://github.com/theonewizard/OpenNote/actions/runs/44969840250): the package tests, the Mac UI tests, and the UI tests on the image's first iPhone and iPad simulators (Xcode 27.1, iOS 27.0). P4-05, P4-06 and P4-07 are COMPLETED from that; P4-03 and P4-08 stay TESTING.

## Not verified

- On the Mac: the sign-in sheet. Locally `automationmodetool` reports "This device requires user authentication to enable Automation Mode", and driving the pointer on Flemming's desktop was not started without him; CI runs the Mac UI test but has no server to sign in to.
- The camera, the share sheet itself (the extension is registered; the inbox import was checked with a file placed by hand), Scribble with a Pencil, a hardware keyboard, the App Intent, any real device (no signing team).

## Noticed, not changed

- `make up-deps` fails on this ARM Mac with Podman: the `opennote-postgres` image build stops at `package pgvector_18-0.8.7-2PGDG.rhel10.3.aarch64 cannot be verified and repo pgdg18 is GPG enabled` (the pinned PGDG key does not verify the aarch64 package). CI builds on x86-64 only.
- Port 5173, Vite's default and the one `docs/development/setup.md` assumes, was taken on this Mac by another project's dev server; `npm run dev -- --port 5273 --strictPort` avoided it.
- `docs/IMPLEMENTATION_STATUS.md`, "Verified where", still describes "Local" as the Linux container of the earlier sessions.
- `apple/Packages/OpenNoteSync/Sources/OpenNoteSync/SyncEngine.swift` has two "no 'async' operations occur within 'await'" warnings from before this change.
- The main checkout has two untracked files that are not this session's: `.conversations/2026-11-20-understand-knowledge-graph.md` and `AGENTS.md`.
