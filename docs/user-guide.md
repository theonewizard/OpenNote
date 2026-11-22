# User guide

What OpenNote does for you today, and what it does not do yet (P8-07). OpenNote is pre-release: the server and the web app work; the Mac, iPhone and iPad apps work when built from source and are not yet distributed ([ROADMAP.md](ROADMAP.md)).

## Your notes are plain files

A vault is a folder of Markdown files, the same layout Obsidian uses. OpenNote reads and writes those files and nothing else is authoritative: the database and the search index can be rebuilt from them.

- A note is saved byte for byte as you wrote it. OpenNote does not reformat it or add `modified:` to existing notes. A note created through OpenNote gets an `id` in its frontmatter.
- You can keep editing the vault with Obsidian or any editor. When a file changes on disk, OpenNote picks the change up and records it as a new revision.
- Every save keeps the previous revision, so nothing is lost when you overwrite a note.
- Tags (`#tag` or `tags:` in frontmatter), `[[wiki links]]` and `- [ ]` tasks are indexed, so search and backlinks know about them.

## The web app

Open the address your administrator gave you and sign in with your username and password, or with the button for your organization's sign-in (OIDC) if the server offers one. **Sign out** at the top right ends the session; the notes cached in this browser stay there, but the browser no longer opens them without signing in again.

The web app has three panes: folders, tags and the views All notes, Favorites, Archive and Trash on the left, the notes in the chosen folder in the middle, and the editor on the right. On a narrow screen such as a phone the panes stack.

- **Notes and folders.** **New note** and **New folder** create them in the open folder. Above the editor, **Rename** moves or renames a note and, unless you untick it, updates the links to it in other notes; **Delete** moves it to the Trash, where **Restore** brings it back. A folder's **Rename** and **Delete** sit above its note list; only an empty folder can be deleted.
- **Favorites, archive, tags.** **Favorite** and **Archive** above the editor set `opennote: favorite` or `archived` in the note's frontmatter. Archived notes show only under Archive. **Tags** edits the note's tags; the tag list on the left filters the notes. The list can be sorted by path, title or date.
- **Search.** The search field at the top lists the filters of the search grammar while you type; results show the matching words highlighted.
- **Attachments.** **Attach** uploads a file next to the note and inserts `![[file name]]` at the cursor. Images show under their line in the editor. Ctrl-click (⌘-click on a Mac) a `[[link]]` or embed to open it; a link to a note that does not exist yet creates it. A folder's attachments are listed under its notes: images preview there, a PDF opens in a new tab.
- **Settings.** Create vaults; as a vault's owner, rename it, switch AI features and syncing of the `.obsidian` folder, change members' roles, and delete it (its files stay on the server). An administrator can add members. Signed-in apps can be revoked under Devices.

- **Saving.** Edits are saved 1.5 seconds after you stop typing, and at once with Ctrl+S (⌘S on a Mac). The status line says `Saved`, `Unsaved changes`, `Saving…` or `Save failed, retrying on the next edit`. The browser warns you before you close a tab with unsaved changes.
- **Someone else saved first.** If the note changed on another device since you opened it, OpenNote does not overwrite that change. It shows "This note was changed elsewhere": your edits stay in the editor, unsaved. Copy them, choose **Reload note**, and paste them back where they belong.
- **Read-only notes.** In a vault where you are a viewer, notes open read-only. A note that is not UTF-8 text opens read-only too, so its bytes are never changed.
- **Not connected.** The status line shows this when the web app cannot reach the server.
- **Offline.** Notes you have opened stay readable and editable without a connection, and sync when it is back. Creating, renaming, deleting, tagging and uploading need the server.

## The Mac, iPhone and iPad apps

The apps keep the vault as real files on the device, so they work without a connection and without an account; signing in adds sync.

- **Starting.** Enter your server's address (`https://…`) and choose **Sign In**: the server's own sign-in page opens in the system's sign-in sheet, and the app never sees your password. Then pick one of your vaults. On the Mac you choose the folder the vault lives in, and Obsidian can open the same folder. On iPhone and iPad the vault is a folder under OpenNote in the Files app. Or skip the account: **Open a Folder Without an Account** (Mac) or **Use on This Device Only**.
- **Three panes.** Folders, the notes of the folder (newest first) and the note. An iPhone shows one at a time; an iPad in landscape shows all three.
- **Notes.** **New Note** makes `Untitled` in the open folder. **Rename** takes a name or `Folder/Name`, which moves the note and creates the folder; links to the note in other notes are not updated. **Delete** moves the note out of the vault into the app's recovery area.
- **Saving.** Edits are saved 1.5 seconds after you stop typing, when you leave the note, and with ⌘S. If the note changed elsewhere while you were editing (another device, Obsidian), nothing is overwritten: a bar says so and **Reload** takes the other version. If you leave the note instead, your edits are kept beside it as `… (unsaved edits)`.
- **Search.** The search field finds notes by name and by text.
- **Attachments.** **Attach** copies a file next to the note and adds `![[file name]]` at the end of it. On the Mac you can also drop files on the note; on iPhone and iPad **Take Photo** attaches a picture from the camera.
- **Sync.** The line under the folders says `On this device only`, `Syncing…`, `Synced` with the time, `Signed out`, or what went wrong. Changes from other devices arrive within seconds while the app is open. Sign out, close the vault or sync at once under Settings (Mac) or the account button (iPhone, iPad). Signed-in apps are listed, and can be revoked, under Devices in the web app.
- **Capture.** On iPhone and iPad, **OpenNote** in the share sheet saves the shared text or web address as a note in the `Inbox` folder the next time the app opens. The shortcut **Capture Note** (Shortcuts, Spotlight, Siri) and links of the form `opennote://capture?text=…` do the same on every device.
- **Notifications.** If the server refuses one of your changes, the app tells you with a notification, once per file.
- **Mac menus.** New Note ⌘N, New Window ⌥⌘N, Save ⌘S, Attach File ⇧⌘A, Show in Finder ⇧⌘R, Search Notes ⌥⌘F, Sync Now ⌃⌘S; Rename and Delete are in the Note menu. An iPad with a keyboard has the same shortcuts.

Not in the apps yet: tags, favorites, the Trash, version history, the list of sync conflicts, tasks and reminders. Use the web app for those.

## Search

The search grammar combines words with filters such as `tag:project`, `notebook:Work`, `has:task` and `after:2026-09-01`. The full grammar is in the [API contract](api/api-contract.md) §5.

## Not there yet

Sharing a vault from the apps, reminders and the AI features are on the [roadmap](ROADMAP.md) and not part of what you can use today.
