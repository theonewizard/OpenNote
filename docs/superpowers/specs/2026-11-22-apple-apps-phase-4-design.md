# Apple apps, Phase 4 completion (P4-03, P4-05 to P4-08) — design

Date: 2026-11-22. Plan and rulings `R-P4-nnn`: [2026-11-22-apple-phase-4-plan.md](../plans/2026-11-22-apple-phase-4-plan.md). Record: [.conversations/2026-11-22-apple-phase-4.md](../../../.conversations/2026-11-22-apple-phase-4.md).

## Intent

Flemming, 2026-11-22: "Build what is need to complete Phase 4." Phase 4 is the Apple applications (milestone M4, "Native applications functional"). The packages are done (P4-01, P4-02, P4-04) and the sync engine exists (P5-03) but has never talked to a real server. Open rows: login and Keychain (P4-03), the macOS app (P4-05), the iOS app (P4-06), the iPadOS layout (P4-07), and share extension, quick capture and notifications (P4-08). The apps are still the Phase 0 placeholder window.

## Goals

- A person can sign in to an OpenNote server from the Mac and the iPhone, pick a vault, and read, write, create, rename, delete, search and attach in it, offline included; edits sync through the existing engine.
- The Mac keeps the vault in a folder the user chooses (Obsidian can open it); iOS keeps it in the app's Documents folder, visible in Files.
- Each row's acceptance criterion in the roadmap is met and checked by a test that runs offline.

## Non-goals

Left to the rows that own them: conflict list, history, device list and the sync status screen (P5-05, P5-06, P5-10), reminder notifications (P6-02), tasks, templates, backlinks and tag views (Phase 6), document scanning (P6-06), background sync on iOS, widgets, signing, notarization and TestFlight (P8-08, need Flemming's Apple account).

## Anti-goals

- No second way to write a vault: every write goes through `OpenNoteStorage.Vault` (never-clobber, recovery-area deletes).
- No token anywhere but the Keychain; none in `UserDefaults`, logs or the shared App Group container.
- No logic in the app targets that deserves a unit test: it goes in a package, because the app targets only have UI tests.

## Approaches

1. **Local-first app over the vault folder, sync engine beside it (chosen).** The app reads and writes the folder through the stateless `Vault`; the engine, when signed in, scans the same folder each round and syncs it, exactly as it treats Obsidian or Finder ("changes made outside the engine"). The app works without an account, UI tests need no server, and nothing in the engine changes except a callback after each round.
2. **Server-backed app like the web client.** Lists, search and note actions through the REST API with a cache. It gives tags, snippets and the search grammar for free, but offline editing, the Files folder and Obsidian compatibility (the reason native clients keep a real vault, spec §5.4) would all need the first approach underneath anyway.
3. **The app goes through the engine's `LocalVault`.** One owner of the state database, but the engine needs a server API to exist, so a signed-out app would need a second path. Rejected for that.

## Design

### Login (P4-03), in `OpenNoteAPI`

OAuth 2.0 authorization code with PKCE against the server's own endpoints (ADR-0012): `GET /api/v1/auth/authorize` with `client_id=opennote-apple`, `redirect_uri=opennote://auth/callback`, an S256 challenge and a random `state`, opened in `ASWebAuthenticationSession` (SwiftUI's `webAuthenticationSession` environment value, callback scheme `opennote`). The callback's `state` is compared, the `code` goes to `POST /api/v1/auth/token` with the verifier, the device name and platform; the answer (access token, expiry, refresh token, device id) is stored as one Keychain item per server.

| Piece | Job |
|---|---|
| `ServerAddress` | Parses what the user typed; `https` only, except `http` for loopback hosts |
| `PKCE` | Verifier (32 random bytes, base64url) and S256 challenge |
| `OAuthClient` | Authorize URL, callback check, code exchange and refresh, over the generated client; a failed token call never carries its request (code, verifier, refresh token) into an error or a log |
| `CredentialStore`, `KeychainStore` | Load, save and delete the credentials (`kSecClassGenericPassword`, this device only, after first unlock) |
| `Session` (actor) | Hands out a valid access token, refreshing 60 s before expiry, one refresh at a time; an `invalid_grant` deletes the credentials and reports signed out; signing out tells the server and forgets the credentials |
| `BearerAuth` (middleware) | Adds `Authorization`; on a 401 refreshes once and repeats the request when its body can be replayed |
| `urlSessionTransport()` | swift-openapi-urlsession (the dependency the spec §5.4 and the sync engine design name for this step), 60 s request timeout |
| `Client(server:…)` | The generated client reading the server's timestamps, which have fractional seconds except when they are zero |

### The app (P4-05, P4-06, P4-07), in `apple/Apps`

- **State.** `AppModel` (one per process): the configuration in `UserDefaults` (`serverURL`, `vaultID`, `vaultFolder`), the open vault, its file list from `Vault.scan` (off the main thread, reusing the last scan's hashes), the session and the engine task. `NoteWindow` (one per window): selected folder and note, the editor document with the hash it was loaded at, search text, and the actions the menus call.
- **Start.** No vault: a welcome screen with a server address and **Sign In**, or a local vault with no account (macOS: choose a folder; iOS: `Documents/Notes`). After signing in the server's vaults are listed; the Mac then asks for the folder, iOS uses `Documents/<vault name>`.
- **Three panes** in a `NavigationSplitView`: folders ("All Notes" plus every folder that holds a note), the notes of the folder newest first, the editor. iPhone collapses to a stack; iPad shows all three in landscape.
- **Editing.** `MarkdownEditor` on an `EditorDocument`; saved 1.5 s after the last keystroke, on ⌘S, and when the note or the app goes away, with `Vault.write(expectedBase:)`. If the file changed on disk meanwhile nothing is overwritten: a banner says so and **Reload** takes the disk version (the web app's rule); leaving the note instead keeps the edits as a new note beside it, `… (unsaved edits).md`.
- **Note actions.** New note (`Untitled.md`, then `Untitled 1.md`…), rename or move (type `Folder/Name`), delete (to the recovery area). Rename writes the new path and removes the old one; the engine reports that as a move.
- **Search.** The search field filters by name and by content (a linear scan of the notes, off the main thread).
- **Attachments.** **Attach** (file picker, both platforms), files dropped on the editor (macOS) and **Take Photo** (iOS camera) copy the file next to the note under a sanitized, unused name and append `![[name]]` to the note.
- **Refresh.** The list reloads after every engine round, after each local action, and when the app becomes active, so Obsidian and Finder edits show without a file watcher.
- **Sync.** Signed in with a vault: `SyncEngine.run()` over `OpenAPISyncAPI` with the transport and `BearerAuth`; saves call `notifyLocalChange()`. The toolbar shows one status line (local only, syncing since, last error, signed out).
- **macOS.** Multiple windows (`WindowGroup`), a Settings window (account, vault, sync now, sign out), menu commands with shortcuts (New Note ⌘N, New Window ⌥⌘N, Save ⌘S, Attach ⇧⌘A, Search ⌥⌘F, Show in Finder ⇧⌘R, Sync Now ⌃⌘S; Rename and Delete without one, since ⌘⌫ belongs to the text view).
- **iOS and iPadOS.** `UIFileSharingEnabled` and `LSSupportsOpeningDocumentsInPlace` expose the vault in Files; `NSCameraUsageDescription` for the camera. The same commands are the iPad's keyboard shortcuts. Pencil: standard controls and an unmodified `UITextView`, so Scribble and pointer hover work as the system provides them.

### Share, capture, notifications (P4-08)

- **Share extension (iOS).** Takes text and web URLs from the share sheet and writes one Markdown file into the App Group container `group.dev.opennote.OpenNote/Inbox`. The app moves those files into the vault's `Inbox/` folder when it becomes active. The extension holds no token and never touches the vault.
- **Quick capture.** One function, `capture(text)`, writing `Inbox/<first line>.md`. It is reached from an App Intent ("Capture Note": Shortcuts, Spotlight, Siri, the Action button; both platforms) and from `opennote://capture?text=…`, which the UI test drives. Text is capped at 100 000 characters.
- **Notifications.** A local notification when a sync round leaves a newly flagged file (the server rejected an edit, or a file was restored): the one thing that needs the user while the window is elsewhere. Permission is asked the first time there is something to say.

## Constraints

- Swift 6 language mode, strict concurrency; macOS 15, iOS 18 (D3). XcodeGen project (ADR-0011); every package pin exact with its `Package.resolved` committed.
- Tests offline: package tests fake the HTTP transport; UI tests use a local vault.
- Builds are signed ad hoc ("Sign to Run Locally"), which needs no team: the iOS App Group entitlement only takes effect in a signed build. Device builds need a team (P8-08).

## Left to the builder

File layout inside `apple/Apps`, view composition, accessibility identifiers, and the wording of messages.

## Known limits (accepted)

- One vault per installation; switching means closing the vault in Settings.
- The Mac stores the folder as a path, which is enough for an app that is not sandboxed; a sandboxed (App Store) build needs a security-scoped bookmark.
- Empty folders are not shown (a folder exists in the list through its notes), and attachments are appended to the note, not inserted at the cursor.
- Search is a linear scan; an FTS index in the state database is the upgrade when a vault is large enough to notice.
