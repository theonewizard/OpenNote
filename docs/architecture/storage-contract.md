# Storage Contract

Status: Proposed (2026-10-17). Implements design §3, §4, §15.2.2–2.3, §15.8. Decisions: [ADR-0002](adr/0002-obsidian-vault-source-of-truth.md), [ADR-0006](adr/0006-note-identity.md), [ADR-0017](adr/0017-history-store-outside-database.md).

This contract binds every component that reads or writes a vault: the backend `vaults`/`notes`/`sync` modules, `OpenNoteCore`/`OpenNoteStorage` on Apple platforms, and the web cache. The same rules are implemented in Python and Swift and checked against the same [compatibility corpus](../development/testing-strategy.md#3-compatibility-corpus).

## 1. Vault

A vault is a directory tree. Its root is identified by `.opennote/config.json` (if absent, the directory is a plain Obsidian vault that OpenNote can open read-write; the config file is created only when the user registers the vault with OpenNote, never on open).

### 1.1 File classification

Evaluated on the vault-relative path, first match wins:

| Rule | Classification | OpenNote behaviour |
|---|---|---|
| Any path segment starts with `.` (e.g. `.obsidian/`, `.trash/`, `.git/`, `.DS_Store`) | Ignored | Never read for content, never written, never synced. Exceptions below |
| `.opennote/config.json` | Vault config | Read; written only by explicit settings changes |
| `.obsidian/` | Obsidian config | Preserved; optionally synced as opaque files when the vault setting `sync_obsidian_config` is on (default off) |
| `*.md` (case-insensitive extension) | Note | Parsed per §2 |
| `*.canvas`, `*.base` | Obsidian structured file | Treated as an attachment (opaque), synced, never modified |
| Name matches OS cruft (`Thumbs.db`, `desktop.ini`, `Icon\r`) | Ignored | — |
| Name ends with `.opennote-tmp` | In-flight write | Ignored; stale ones (> 1 h) cleaned by reconciliation |
| Anything else | Attachment | Opaque bytes, synced, never modified |

Symlinks are not followed. A symlink inside a vault is reported as an unsupported entry and skipped.

### 1.2 `.opennote/config.json`

Portable settings only. No device IDs, cursors, caches or credentials.

```json
{
  "schema_version": 1,
  "vault_id": "0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c",
  "name": "Work",
  "attachments_folder": "Attachments",
  "templates_folder": "Templates",
  "daily_notes": { "folder": "Personal/Journal", "format": "YYYY-MM-DD" },
  "new_note_folder": "Inbox"
}
```

Unknown keys are preserved on rewrite. A higher `schema_version` than the client understands makes the client open the vault read-only and tell the user to update.

### 1.3 Data that must live outside the vault

Search indexes, embeddings, thumbnails, sync state, merge bases, outbox, logs and device settings. Native clients keep them in Application Support (macOS) or the app container's Library (iOS); the server keeps them in PostgreSQL and the history volume.

## 2. Notes

### 2.1 Byte preservation

The stored bytes of a note are the note. OpenNote must:

- Preserve encoding: UTF-8 with or without BOM. A note that is not valid UTF-8 is opened read-only and synced as opaque bytes.
- Preserve line endings per file (LF, CRLF or mixed). New lines inserted by OpenNote use the file's dominant ending; new files use LF.
- Preserve the presence or absence of a trailing newline.
- Never re-render Markdown. Edits from any editor are applied as text changes to the original string.
- Never normalize whitespace, list markers, heading styles, escaping, or table alignment.

Invariant tested on every corpus file: `write(read(bytes)) == bytes`, and for each metadata edit, the bytes outside the edited YAML node are unchanged.

### 2.2 Frontmatter

- Frontmatter exists only if the file's first line (after an optional BOM) is exactly `---` and a later line is exactly `---` (or `...`). Otherwise the whole file is body.
- The raw frontmatter text is kept verbatim. Parsing is for reading properties; editing uses a round-trip YAML editor (Python `ruamel.yaml` round-trip mode; Swift equivalent targeted at the same corpus) that preserves key order, comments, quoting and flow style of untouched nodes.
- If the YAML is invalid, the note is still listed, readable and body-editable; properties are reported as `null` with a `frontmatter_error` and metadata edits are refused with a clear error.
- Recognized properties (Obsidian-standard): `tags`, `aliases`, `cssclasses`, plus `id`, `title`, `created`, `modified` when present. `tags` and `aliases` accept a list or a single string (comma-separated legacy form accepted on read, list written on edit).
- OpenNote-specific properties live under a single `opennote:` mapping (e.g. `favorite`, `archived`, `status`). OpenNote never creates other top-level keys except `id` (see §2.4), `tags` and `aliases` when the user edits those.
- OpenNote never auto-writes `created` or `modified`. If present they are user data and are preserved. Note timestamps shown in the UI come from revisions.

### 2.3 Body syntax recognized (read-only extraction)

| Syntax | Extracted as | Notes |
|---|---|---|
| `[[Target]]`, `[[Target\|Alias]]`, `[[Target#Heading]]`, `[[Target#^block-id]]`, `[[#Heading]]` | Outgoing link | Target resolution in §2.5 |
| `![[Target]]`, `![[image.png\|300]]` | Embed | Same resolution; attachment or note |
| `[text](relative/path.md)`, `[text](<path with spaces.md>)`, URL-encoded paths | Outgoing link | External `scheme://` URLs recorded separately |
| `#tag`, `#nested/tag` | Inline tag | Not inside code spans, fenced/indented code, HTML comments, `%%comments%%`, URLs or headings' leading `#` |
| `> [!type]` callouts, `^block-id`, `%%comment%%`, `$math$`, footnotes, HTML | Preserved | Recognized for rendering; never rewritten |
| `- [ ]` / `- [x]` | Task (Phase 6) | Toggle edits change exactly one character |

Anything else is preserved as text.

### 2.4 Identity

- If frontmatter has `id` and it is a valid UUID, that is the note's identity. Duplicate IDs in a vault (e.g. a copied file) are resolved by keeping the ID on the older revision and giving the newer file a server-assigned file ID; nothing is written to the file.
- Otherwise the note's identity is a server-assigned **file ID** (UUIDv7) stored in the index, not in the file.
- OpenNote writes `id` only into notes it creates, or when the user runs the explicit per-vault "Normalize metadata" action (dry-run diff first). Opening, viewing or editing an existing note never inserts an `id` (decision D5).
- Renames through OpenNote carry the identity in the move operation. Renames done outside OpenNote (Obsidian, Finder) are detected as delete + create within one reconciliation batch with an identical content hash (or matching `id`) and recorded as a move.
- Attachments have a server-assigned file ID; same rename detection rules.

### 2.5 Link resolution (Obsidian-compatible)

1. Strip `#heading`/`#^block` and `|alias`. If the target has no extension, append `.md` for lookup.
2. If the target contains `/`, resolve relative to the vault root; if not found, relative to the linking file's folder.
3. Otherwise match by file name across the vault; if several match, prefer the one in the linking file's folder, then the shortest path, then lexical order.
4. Comparison is NFC-normalized and case-insensitive (Obsidian behaviour), which is also why case-fold duplicates are disallowed (§3.2).
5. Unresolved links are kept and reported as unresolved.

OpenNote does not rewrite links on rename in v1. Optional "update links on rename" (Obsidian's setting) is a Phase 6 feature and, when on, produces a single multi-file revision batch the user can undo.

## 3. Paths

### 3.1 Representation

Vault-relative, `/`-separated, no leading `/`, Unicode NFC. On macOS/iOS, names read from disk are normalized to NFC before comparison; names written to disk use the NFC form.

### 3.2 Validation (shared rule set, exposed as `GET /api/v1/meta/path-rules`)

Rejected:

- Empty segments, `.` or `..` segments, absolute paths, backslashes, NUL and control characters.
- Characters `* " \ / < > : | ?` in a segment (unsafe on Windows/iOS/Obsidian) and `# ^ [ ] |` in note names (break wiki-links).
- Segments ending in a space or `.`; segments longer than 255 UTF-8 bytes; total path longer than 1024 bytes.
- Reserved Windows names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`) as a base name.
- A path whose case-folded NFC form equals an existing different path in the same folder (case-fold collision).
- A leading `.` (would be ignored per §1.1).

Existing files that break these rules (e.g. created on Linux by another tool) are indexed and readable, flagged `path_warning`, and are not synced to clients whose filesystem cannot represent them until renamed.

### 3.3 Containment

Every resolved absolute path must be inside the vault root after `realpath`; operations use `openat`-style directory handles on the server (Python: `os.open` with `dir_fd`, `O_NOFOLLOW`) so a concurrently swapped symlink cannot escape.

## 4. Writes

1. Write to `<dir>/.<name>.<random>.opennote-tmp` in the target directory (dot prefix keeps Obsidian from showing it).
2. `fsync` the file, `rename` over the target (atomic on POSIX/APFS), `fsync` the directory.
3. On Apple platforms use `NSFileCoordinator` for writes so other presenters (Files app, Obsidian on macOS) see a coordinated change.
4. Before overwriting, compare the on-disk hash with the expected base hash; if it changed, abort and hand the external change to the sync engine instead (never clobber an external edit).
5. Deletes from OpenNote move the file to the vault's history (server) or to a local recovery area (clients) before unlinking; nothing is hard-deleted on first delete.

## 5. Change detection

- Primary: filesystem events (inotify via `watchdog` on the server, FSEvents on macOS, `NSFilePresenter` on iOS), debounced 500 ms per path.
- Safety net: reconciliation scan comparing `(size, mtime_ns, inode)` and, on mismatch, SHA-256 content hash; runs at startup, after watcher overflow, and every 15 minutes (configurable).
- An event whose resulting content hash equals the hash OpenNote itself last wrote for that path is ignored (loop prevention).
- `mtime` is a hint for when to re-hash, never a source of truth.

## 6. Hashing

`content_hash = "sha256:" + lowercase hex` of the exact bytes. Used for change detection, blob addressing and deduplication.

## 7. History store (server)

Every committed revision's bytes are stored once, content-addressed, at `<history_root>/<vault_id>/objects/<aa>/<bbbb…>` (zstd-compressed), outside the vault and outside PostgreSQL. Revision metadata (file ID, revision, path, hash, device, time, op) is in PostgreSQL and is also appended to `<history_root>/<vault_id>/log/YYYY-MM.jsonl` so history can be rebuilt without the database. Retention per decision D6.
