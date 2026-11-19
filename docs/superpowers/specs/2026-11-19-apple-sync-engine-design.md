# Apple sync engine (P5-03) — design

Status: implemented in `apple/Packages/OpenNoteSync` (PR #83). Protocol: [sync-protocol.md](../../architecture/sync-protocol.md) §§2.2, 4, 5, 9. Record and rulings `R-AS-nnn`: [.conversations/2026-11-19-apple-sync-engine.md](../../../.conversations/2026-11-19-apple-sync-engine.md).

## Pieces

| Piece | Where | Job |
|---|---|---|
| Sync state | `OpenNoteStorage/StateStore+Sync.swift` (state database version 2) | `sync_files` and `outbox` tables beside the scan table; cursor and the reconcile mark in `meta` |
| `SyncAPI` | `OpenNoteSync/SyncAPI.swift` | The seven server calls the engine makes, as plain Swift values |
| `OpenAPISyncAPI` | `OpenNoteSync/OpenAPISyncAPI.swift` | `SyncAPI` over the generated client; blob `HEAD`/`PUT` and `GET /events` by hand through the same transport and middlewares (R-AS-003) |
| `SyncEngine` | `OpenNoteSync/SyncEngine.swift` | The round and the loop, one actor per vault |

The app supplies the transport (swift-openapi-urlsession when the app is wired, P4-03) and a middleware with the device's bearer token.

## Client state per file

| Column | Meaning |
|---|---|
| `file_id` | The server's id (UUIDv7, made here for a `create`) |
| `local_path` | Where the file is in the vault; null when it is not on disk |
| `base_revision`, `base_hash`, `base_path` | The server revision the local copy derives from (0 = none; a null hash with a revision = a tombstone) |
| `remote_revision`, `remote_hash`, `remote_path` | The newest revision pulled; written to disk once the copy is clean |
| `flag`, `note` | `rejected` (the server's reason in `note`; never pushed or overwritten until the user clears it) or `restored` |

A file is clean when its hash in the scan table equals `base_hash`, or, with no `local_path`, when the base is a tombstone or nothing.

## One round

1. **Expire**: outbox operations older than the tombstone window minus 7 days are dropped and a full reconcile is marked (§5).
2. **Scan**: rescan the vault (only changed files are hashed), then for every file without a pending operation and not rejected: unknown file → `create` (or adopt a pulled file with the same path and bytes), changed bytes → `update`, gone from its path with the same bytes elsewhere → `move`, gone → `delete`, moved away from `base_path` → `move`.
3. **Push**: in outbox order, 100 at a time. Before a `create` or `update` is first sent its hash is refreshed to the file's current bytes; after that it is fixed, so a retry repeats it exactly. The blob goes first: `HEAD`, then the whole file up to 8 MiB, or chunks of 8 MiB with `Content-Range` from the `Upload-Offset` the server gives. Results:
   - `applied`: the result is the new base.
   - `merged`: if the file still holds what was pushed, the merged bytes are written and become the base; if it changed again, the merge becomes the base and the file stays dirty for the next push.
   - `conflict`: the edit lives on in the conflict copy, which the pull writes; the original's local copy counts as clean at the pushed bytes, so the server's version replaces it. A `create` on a taken path hands the path to the server's file.
   - `rejected`: flagged. `delete-superseded` instead lets the edit win (the pull writes it back); `file-not-found` (the server forgot the file) turns an edit into a new file flagged `restored`.
   - `duplicate`: read as its first result from the stored fields (R-AS-004).
4. **Pull**: pages from the cursor; each page's entries and the next cursor land in one transaction. On 410, or when marked, a full reconcile: read every snapshot page, record each file, treat a known clean file the server no longer has as deleted (into the recovery area) and a dirty one as `restored`, then pull from the snapshot's cursor. Finally every file whose remote is newer than its base and whose copy is clean is written: content, moves (create at the new path, then the old one into recovery) and tombstones (into recovery). A write that finds the file changed, or the path taken, is left for a later round.

## Loop

`run()` starts a round on start, on `ready` and on every `change` hint for the vault from `GET /api/v1/events` (reconnecting with backoff), 2 s after the last `notifyLocalChange()`, and every 60 s; after a failure it waits 5 s, doubling up to 5 minutes. `lastError` and `flaggedFiles()` are for the sync status UI (P5-10).

## Not in this change

- The conflict list and resolution UI (P5-05) and the version-history UI read the server directly; the engine keeps no `bases` table (R-AS-005).
- Detecting competing sync tools (P5-08).
- App wiring: the URLSession transport, device registration and token refresh, FSEvents calling `notifyLocalChange()` (P4-03).
