# 2026-11-19 — Apple sync engine (P5-03)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Rulings are numbered `R-AS-nnn` (Apple sync) so they cannot collide with the web engine's thread.

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-19 08:10 | Flemming (Phase 5 thread) | "Need CI to run so it is not ready for review" |
| 2026-11-19 08:56 | Coordinator (relaying) | Build the Phase 5 Apple client sync engine (P5-03) in apple/Packages with the generated Swift client, against the merged sync server (PR #55): sync protocol §§2.2, 4, 5, 9, 10 and rulings R-P5-001..014. Web runs in another thread, so stay in apple/. A PR stays draft until CI is green on its head. |

## Rulings

- **R-AS-001** The Swift client was missing every nullable property and parameter: FastAPI writes them as `anyOf: [<schema>, {"type": "null"}]` (110 places), and swift-openapi-generator 1.14.1 treats a `null` subschema as unsupported and silently leaves the property out (`isSchemaSupported`: `case .not, .null: return .unsupported`). The sync engine cannot work without them (`SyncEntry.content_hash`, every `PushResult` field but `status`, the `cursor` query parameter, `Idempotency-Key`, `Content-Range`). The export now rewrites them as `type: [<type>, "null"]` (the same JSON Schema), in its own PR before the engine, because it changes the contract file all clients share. The TypeScript output changes only in comments. The two nullable `$ref`s (`OutgoingLink.resolved`, `VaultPatch.settings`) keep their `anyOf` and stay missing in Swift; nothing on Apple uses them yet.
- **R-AS-002** The round scans first, then pushes and pulls (the protocol's §9 loop listed the scan last). A change made since the last round then goes out in the same round; correctness is the same either way. §9 now shows this order.
- **R-AS-003** Blob `HEAD`/`PUT` and `GET /events` go through the transport and middlewares by hand rather than through the generated methods: the `Upload-Offset` header on a 404 or 409 is not in the OpenAPI document (the generated output has no way to read it), and a `HEAD` 404 has no body for the generated `default` response to decode. Changes, snapshot, push and `GET /blobs` use the generated client. Documenting the 404/409 headers in the server's OpenAPI would let the generated methods do it; left for a contract PR if the web engine wants it too.
- **R-AS-004** A `duplicate` is read as its first result from the stored fields: `original_file_id` in the problem means conflict, no revision means rejected, a content hash (or path, for a move) other than the operation's means merged, else applied.
- **R-AS-005** No `bases` table: base bytes are only for offline diffs, and diffs read revisions from the server (R-P5-007). The conflict list and resolution UI (P5-05) read `/api/v1/conflicts` directly, so the engine does not list conflicts.
- **R-AS-006** An operation's content hash is refreshed to the file's current bytes until it is first sent, then fixed, so a retry after a lost response is byte-identical (I4). A sent operation whose bytes are gone from disk is dropped only if `HEAD` says the server lacks its blob (the commit needs it, so it never applied); the next scan sends the current bytes.
- **R-AS-007** `rejected` with `file-not-found` on an update or move (the server forgot the file after its tombstone window) turns the local file into a new file flagged `restored`, the same rule as the full reconcile's "known, missing from the snapshot, dirty". `delete-superseded` clears the delete so the pull writes the winning edit back.
- **R-AS-008** The engine owns its `LocalVault` (made from the vault and support URLs), so no non-Sendable value crosses into the actor. The editor's own `LocalVault` on the same state database is fine: SQLite in WAL mode, and every write checks the bytes on disk.
- **R-AS-009** No URLSession transport dependency yet: the engine takes any `ClientTransport`; the app wiring (P4-03) adds swift-openapi-urlsession. OpenNoteSync names swift-openapi-runtime and swift-http-types directly because it imports them; both were already pinned in its `Package.resolved`.
- **R-AS-010** Files of kind `config` in pulled entries are skipped: the vault scan never reads them, so they could not be pushed back, and the storage layer creates only notes and attachments.
