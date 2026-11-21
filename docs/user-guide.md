# User guide

What OpenNote does for you today, and what it does not do yet (P8-07). OpenNote is pre-release: the server and the web app work, and the Apple apps are still being built ([ROADMAP.md](ROADMAP.md)).

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

## Search

The search grammar combines words with filters such as `tag:project`, `notebook:Work`, `has:task` and `after:2026-09-01`. The full grammar is in the [API contract](api/api-contract.md) §5.

## Not there yet

Sync to the Apple apps, sharing, reminders and the AI features are on the [roadmap](ROADMAP.md) and not part of what you can use today.
