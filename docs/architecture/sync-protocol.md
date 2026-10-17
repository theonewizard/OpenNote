# Synchronization Protocol

Status: Proposed (2026-10-17), protocol version `1`. Implements design §7 and §15.9. Decision: [ADR-0005](adr/0005-revision-based-sync.md). Prototype in Phase 1 (roadmap P1-12), full implementation in Phase 5.

## 1. Goals and invariants

The protocol is judged by these invariants, which the simulation suite checks after every randomized run:

| ID | Invariant |
|---|---|
| I1 | **No acknowledged loss.** Any content a client persisted locally is, after the client syncs, either part of a server revision or stored as a conflict copy. |
| I2 | **No silent overwrite.** A write based on revision *n* never replaces revision *m > n* without a successful three-way merge or a conflict record. |
| I3 | **Convergence.** When all clients are online and idle, every replica's file set and bytes equal the server's. |
| I4 | **Idempotency.** Replaying any request (retry, duplicate delivery) produces the same server state as one delivery. |
| I5 | **No loops.** Applying a pulled change never generates a push of that same change. |
| I6 | **Order independence from clocks.** No decision depends on device or server wall-clock time. |

## 2. Model

### 2.1 Server state per vault

| Concept | Definition |
|---|---|
| File | Identified by `file_id` (UUIDv7, or the note's frontmatter `id`). Has `path`, `kind` (`note`/`attachment`/`config`), `revision`, `content_hash`, `size`, `deleted` |
| Revision | Per-file integer, starts at 1, incremented by exactly 1 per committed change (content, path, or delete/undelete) |
| Change sequence (`seq`) | Per-vault, strictly increasing 64-bit integer assigned at commit. Every committed revision gets one `seq` |
| Cursor | Opaque string encoding `(vault_id, seq, protocol_version)`. Clients store it; only the server interprets it |
| History | Every revision's bytes in the content-addressed history store ([storage contract §7](storage-contract.md#7-history-store-server)) |
| Tombstone | A revision with `deleted = true`. Kept for at least the retention window (default 90 days) so offline clients learn about deletes |

Commits are serialized per vault (PostgreSQL row lock on the vault's sequence row), which keeps `seq` gap-free and makes conflict decisions deterministic.

### 2.2 Client state (outside the vault)

| Table | Contents |
|---|---|
| `files` | `file_id`, `path`, `base_revision`, `base_hash`, `local_hash`, `kind`, `deleted` |
| `bases` | Base bytes for each note at `base_revision` (needed only to show diffs offline; the merge itself runs on the server) |
| `outbox` | Durable ordered operations, each with a `client_op_id` (UUIDv7) |
| `meta` | `device_id`, `cursor`, protocol version |

A local file is **dirty** when `local_hash != base_hash`.

## 3. Operations

| Op | Fields | Server precondition |
|---|---|---|
| `create` | `client_op_id`, `file_id` (client-generated UUIDv7), `path`, `kind`, `content_hash` | Path free (case-fold, NFC); blob present |
| `update` | `client_op_id`, `file_id`, `base_revision`, `content_hash` | Blob present |
| `move` | `client_op_id`, `file_id`, `base_revision`, `new_path` | New path valid and free |
| `delete` | `client_op_id`, `file_id`, `base_revision` | — |
| `restore` | `client_op_id`, `file_id`, `from_revision` | Revision exists in history |

Content travels as content-addressed blobs (`PUT /api/v1/blobs/{sha256}`), so an operation is small and a retried upload is free. Large blobs use chunked, resumable upload (`Content-Range`, 8 MiB chunks) from Phase 5.

## 4. Pull

`GET /api/v1/sync/{vault_id}/changes?cursor=…&limit=500`

Returns ordered entries `{seq, file_id, revision, path, kind, content_hash, size, deleted, device_id, op}` and a `next_cursor`, `has_more`. Clients apply entries in order:

| Local state for `file_id` | Action |
|---|---|
| Unknown or clean | Download blob if needed, write atomically, set `base_* = local_* = remote`. Record the written hash so the watcher ignores it (I5) |
| Dirty | Do not touch the file. Record the remote revision; the pending `update` will be merged by the server on push |
| Locally deleted (pending `delete`) | Keep pending; server decides on push |

A cursor older than the tombstone retention window gets `410 Gone`; the client then performs a **full reconcile**: fetch the complete file list (`GET /sync/{vault_id}/snapshot`), compare hashes, and turn every local difference into ordinary operations. Full reconcile never deletes local content that the server does not know about; it creates it instead.

Change notifications arrive over `WSS /api/v1/events` as `{vault_id, seq}` hints. The event channel is advisory; correctness depends only on pull.

## 5. Push

`POST /api/v1/sync/{vault_id}/push` with up to 100 operations, header `Idempotency-Key` = batch ID. Each operation is processed in order and independently; the response lists one result per operation:

| Result | Meaning | Client action |
|---|---|---|
| `applied` | Committed as `revision`, `seq` | Set base to the result; remove from outbox |
| `merged` | Server merged with newer revision; result is a new revision whose bytes differ from what the client sent | Download merged blob, write if file still equals what was pushed, else leave dirty for next push |
| `conflict` | Unsafe merge. Server revision stays current; the client's version committed as a new file (conflict copy) | Pull both; show conflict in UI |
| `rejected` | Validation error (invalid path, quota, permission) with problem details | Keep local content, surface error, do not retry automatically |
| `duplicate` | `client_op_id` already processed; returns the original result | Same as original |

Server keeps `client_op_id` results for 30 days (I4).

## 6. Merge rules (server-side, single implementation)

Merging runs only on the server, using history as the merge base, so clients do not each need a merge engine (design §15.2.6, no duplicated business rules).

For `update` with `base_revision = b < current = c` on a note:

1. Load base `B` (revision `b`), theirs `T` (revision `c`), ours `O` (pushed content).
2. If `O == T`: result `applied` with no new revision (already converged).
3. Split each into frontmatter and body per the storage contract.
4. **Frontmatter:** key-level three-way merge on parsed YAML; a key changed on one side takes that side; changed on both sides to different values is a conflict; the merged YAML is re-emitted by editing `T`'s raw text with the round-trip editor so untouched formatting is kept. Invalid YAML on any side → treat frontmatter as plain text for step 5.
5. **Body:** line-based diff3 (with the file's line endings). Non-overlapping hunks merge; overlapping hunks with different content are a conflict. No conflict markers are ever written into a note.
6. Clean → commit merged bytes as revision `c+1`, result `merged`. Unclean → result `conflict`.

Other cases:

| Concurrent pair | Rule |
|---|---|
| `move` vs `update` | Independent: both apply (path from move, content from update) |
| `move` vs `move` to different paths | Later-committed move wins the path; result `merged` with the final path; both are in history |
| `update` vs `delete` (either order) | **Edit wins**: file is undeleted with the edited content; the delete is recorded as `superseded` and the user is notified |
| `create` vs `create` same path, different `file_id` | Second gets `conflict`; committed at `Name (conflict <device> <yyyy-mm-dd>).md` |
| Attachments (`update` vs `update`) | No merge: second gets `conflict`, kept as conflict copy |

Conflict copies are ordinary files in the same folder named `<name> (conflict <device-name> <yyyy-mm-dd>)<ext>` (suffix ` 2`, ` 3` on collision), plus a `conflicts` record (`file_id`, `copy_file_id`, revisions, status `open`/`resolved`) that the UI lists. Resolving means the user edits/deletes; both versions remain in history.

## 7. Sources of change on the server

Clients are not the only writers. The server vault volume can be edited directly (Obsidian on a mounted share, scripts). The server watcher and reconciliation scan (storage contract §5) turn such changes into operations attributed to `device_id = "server-fs"`, using the file's last-known revision as `base_revision`, and they go through the same commit path. The atomic-write rule (storage contract §4.4) prevents a client-originated commit from clobbering a concurrent on-disk edit: it aborts, the watcher picks up the external edit as revision `c+1`, and the client's op is merged against it.

## 8. Devices and authentication

- A device registers once (`POST /api/v1/devices`), receiving `device_id` and a device-scoped refresh token.
- All sync calls are authorized per vault (`editor` or `owner` to push, `viewer` to pull).
- Revoking a device invalidates its tokens; its unpushed outbox stays on the device.

## 9. Native client loop

```
on start / network up / event hint / timer (60 s) / local change (debounced 2 s):
    push outbox (blobs first, then ops, in order)
    pull until has_more = false
    for each local dirty file without an outbox op (external edit, e.g. Obsidian on macOS):
        enqueue update/create/delete from local scan
```

Local editing never waits for any of this. Each step is resumable from the outbox and cursor; a crash between steps is safe because every server call is idempotent and every local write is atomic.

## 10. Web client

Same protocol, with IndexedDB holding files, bases, outbox and cursor. The browser cache may be evicted; on eviction the client re-pulls from a fresh snapshot (the server is complete), and the outbox lives in a separate store requested with `navigator.storage.persist()`. Unsynced web edits are flagged in the UI.

## 11. Interaction with other sync tools

One sync engine per vault (design §16.B). Clients detect and warn when the local vault is inside iCloud Drive/Dropbox/OneDrive paths or contains `.obsidian/plugins/obsidian-sync` state enabled. The warning is persistent but not blocking.

## 12. Versioning

`protocol_version` is part of the cursor and of `GET /api/v1/meta`. The server supports the current and previous version. Breaking changes require a new version and a migration note in this file.

## 13. Prototype scope (Phase 1, P1-12)

Server-side only: in-process implementation of §§2–6 against a temporary vault and SQLite, plus a simulation harness with N simulated clients, randomized edits/moves/deletes, network partitions, duplicated and reordered requests, and crash points. Exit criterion: invariants I1–I6 hold over 10,000 seeded runs; failing seeds become regression tests.
