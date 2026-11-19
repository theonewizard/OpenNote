# 2026-11-19 — Apple sync engine (P5-03)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Rulings are numbered `R-AS-nnn` (Apple sync) so they cannot collide with the web engine's thread.

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-19 08:10 | Flemming (Phase 5 thread) | "Need CI to run so it is not ready for review" |
| 2026-11-19 08:56 | Coordinator (relaying) | Build the Phase 5 Apple client sync engine (P5-03) in apple/Packages with the generated Swift client, against the merged sync server (PR #55): sync protocol §§2.2, 4, 5, 9, 10 and rulings R-P5-001..014. Web runs in another thread, so stay in apple/. A PR stays draft until CI is green on its head. |

## Rulings

- **R-AS-001** The Swift client was missing every nullable property and parameter: FastAPI writes them as `anyOf: [<schema>, {"type": "null"}]` (110 places), and swift-openapi-generator 1.14.1 treats a `null` subschema as unsupported and silently leaves the property out (`isSchemaSupported`: `case .not, .null: return .unsupported`). The sync engine cannot work without them (`SyncEntry.content_hash`, every `PushResult` field but `status`, the `cursor` query parameter, `Idempotency-Key`, `Content-Range`). The export now rewrites them as `type: [<type>, "null"]` (the same JSON Schema), in its own PR before the engine, because it changes the contract file all clients share. The TypeScript output changes only in comments. The two nullable `$ref`s (`OutgoingLink.resolved`, `VaultPatch.settings`) keep their `anyOf` and stay missing in Swift; nothing on Apple uses them yet.
