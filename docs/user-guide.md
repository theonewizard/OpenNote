# User guide

What OpenNote does for you today, and what it does not do yet (P8-07). OpenNote is pre-release: the server and the web editor work, and the sign-in screen, offline editing and the Apple apps are still being built ([ROADMAP.md](ROADMAP.md)).

## Your notes are plain files

A vault is a folder of Markdown files, the same layout Obsidian uses. OpenNote reads and writes those files and nothing else is authoritative: the database and the search index can be rebuilt from them.

- A note is saved byte for byte as you wrote it. OpenNote does not reformat it or add `modified:` to existing notes. A note created through OpenNote gets an `id` in its frontmatter.
- You can keep editing the vault with Obsidian or any editor. When a file changes on disk, OpenNote picks the change up and records it as a new revision.
- Every save keeps the previous revision, so nothing is lost when you overwrite a note.
- Tags (`#tag` or `tags:` in frontmatter), `[[wiki links]]` and `- [ ]` tasks are indexed, so search and backlinks know about them.

## The web app

Open the address your administrator gave you. The web app has three panes: folders on the left, the notes in the chosen folder in the middle, and the editor on the right. "All notes" at the top of the folder list shows every note. On a narrow screen such as a phone the panes stack.

- **Saving.** Edits are saved 1.5 seconds after you stop typing, and at once with Ctrl+S (⌘S on a Mac). The status line says `Saved`, `Unsaved changes`, `Saving…` or `Save failed, retrying on the next edit`. The browser warns you before you close a tab with unsaved changes.
- **Someone else saved first.** If the note changed on another device since you opened it, OpenNote does not overwrite that change. It shows "This note was changed elsewhere": your edits stay in the editor, unsaved. Copy them, choose **Reload note**, and paste them back where they belong.
- **Read-only notes.** In a vault where you are a viewer, notes open read-only. A note that is not UTF-8 text opens read-only too, so its bytes are never changed.
- **Not connected.** The status line shows this when the web app cannot reach the server or you are not signed in.

The web app has no sign-in screen yet (P3-01). Until it lands, the web app is for development and testing, and scripts use a personal access token ([using-the-api.md](api/using-the-api.md)).

## Search

The search grammar combines words with filters such as `tag:project`, `notebook:Work`, `has:task` and `after:2026-09-01`. The full grammar is in the [API contract](api/api-contract.md) §5.

## Not there yet

Offline editing, sync to the Apple apps, sharing and attachments in the web app, reminders and the AI features are on the [roadmap](ROADMAP.md) and not part of what you can use today.
