# Web sync engine plan (P5-04, with P3-08)

Date: 2026-11-19. Requested by Flemming (web and Apple engines in parallel threads; this one stays in `web/`). Protocol: [sync-protocol.md](../../architecture/sync-protocol.md) §§2.2, 4, 5, 9, 10 against the server of PR #55 ([server plan](2026-11-14-phase-5-sync-server-plan.md), R-P5-001..014). Record: [.conversations/2026-11-19-web-sync-engine.md](../../../.conversations/2026-11-19-web-sync-engine.md).

P3-08 (IndexedDB cache and outbox) had not been built and P5-04 depends on it, so both land together: the editor now saves into IndexedDB and the engine syncs from there.

## What exists

| File | Role |
|---|---|
| `web/src/sync/db.ts` | IndexedDB `opennote-sync-<user id>`: `files`, `outbox` (own store, auto-increment order), `contents` (bytes by `sha256:` hash), `meta` (cursor per vault, cached vault list), `recovery` |
| `web/src/sync/api.ts` | changes, snapshot, push, blob `GET`/`HEAD`/`PUT` (8 MiB `Content-Range` chunks, resume from `Upload-Offset`, 409 offset continues there), timeouts on every call |
| `web/src/sync/engine.ts` | `SyncEngine`: `read`, `edit`, `discard`, `sync`, the loop (`start`/`stop`) and status |
| `web/src/sync/useSync.ts` | one engine per signed-in user (`GET /api/v1/me`), status hook |
| `web/src/mocks/sync-server.ts` | in-memory sync server for unit tests, `npm run dev:mock` and Playwright |

## Rulings (no owner decision needed)

- **R-W5-001** One database per user, named by user id; the last user id is kept in `localStorage` so the app can open that user's cache when it starts offline. A 401 never opens a cache.
- **R-W5-002** One unsent operation per file: a new edit replaces the `content_hash` of an unsent `update`/`create` (pushing successive edits of one file as separate updates on the same base would make the server merge a client with itself). An entry's `base_revision` is fixed when it is first sent, so a retry repeats the same operation and the server answers `duplicate`.
- **R-W5-003** A push batch holds at most one operation per file (up to 100): the next operation on a file needs this one's revision.
- **R-W5-004** `duplicate` carries no original status; the engine reads it from the fields: `original_file_id` in the problem means conflict, a problem without revision means rejected, otherwise applied.
- **R-W5-005** After `merged`, the device takes the merged bytes only if nothing was typed since the push. If something was, the file keeps its old base, so the next push is merged by the server against the merged revision instead of replacing it.
- **R-W5-006** When sync replaces the bytes an open editor was typing on, the editor's next save names the hash it started from; the engine then pushes it against the revision those bytes had (`prev`), so the server merges. An edit on bytes the device never held is refused (`StaleEdit`) and the editor keeps the text, as before.
- **R-W5-007** Note bytes are downloaded before a pulled entry is applied, so a cached note is never shown without them; attachment bytes are fetched only when read.
- **R-W5-008** Pulled tombstones and files missing from a snapshot move to the `recovery` store (kept 30 days); cached bytes nothing refers to are removed after each sync.
- **R-W5-009** The loop syncs on start, `online`, every SSE `ready` and matching `change` hint, every 60 s, 2 s after an autosave and at once after an explicit save (Save button or Ctrl/Cmd+S). Tabs of one user take a Web Lock per vault, so one tab syncs a vault at a time.
- **R-W5-010** Outbox entries older than 83 days (90-day window minus 7) are dropped and a full reconcile follows; reconcile turns any remaining local difference into a fresh operation.
- **R-W5-011** Without a cursor (first start, or an evicted cache) the engine reconciles from the snapshot instead of pulling the whole history.
- **R-W5-012** The note list falls back to the device's cached notes when `GET /notes` cannot be reached, and the vault list to the cached copy; folders are not cached.

## Not in this change

- The web UI still has no create, rename or delete; the engine only produces `create` (reconcile) and `update`. Those operations come with the UI that needs them.
- Conflict list and resolution UI is P5-05; the editor shows a notice naming the conflict copy, and a rejected edit with a Discard button.
- Cross-client end-to-end suite is P5-09.
