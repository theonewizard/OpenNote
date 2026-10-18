# API Contract

Status: Proposed (2026-10-17), API version `v1`. Decisions: [ADR-0012](../architecture/adr/0012-authentication-and-tokens.md), [ADR-0013](../architecture/adr/0013-api-style-and-client-generation.md). The machine-readable contract is `docs/api/openapi.json`, generated from code from Phase 2 onward; where it and this document disagree after Phase 2, the OpenAPI file wins and this document is corrected.

## 1. Conventions

| Topic | Rule |
|---|---|
| Base path | `/api/v1`. Breaking changes require `/api/v2`; additive changes do not |
| Format | `application/json; charset=utf-8`; note bodies also as `text/markdown` |
| Identifiers | UUIDv7 strings |
| Time | RFC 3339 UTC with `Z`, millisecond precision |
| Naming | `snake_case` fields, plural resource nouns |
| Pagination | Cursor based: `?limit=` (default 50, max 500) and `?cursor=`; responses `{ "items": [...], "next_cursor": "…" \| null }` |
| Concurrency | Every mutable resource has `revision`. Responses carry `ETag: "<revision>"`. `PUT`, `PATCH`, `DELETE` require `If-Match`; missing → `428 Precondition Required`, stale → `412 Precondition Failed` with the current resource in the problem's `current` extension |
| Idempotency | `POST` accepts `Idempotency-Key` (UUID); repeat within 24 h returns the original response |
| Errors | RFC 9457 `application/problem+json`; `type` URIs under `https://opennote.dev/problems/<slug>`; `detail` is generic and safe; internals logged server-side only (`CLAUDE.md` §13). Validation errors add `errors: [{ "pointer": "/path", "message": "…" }]` |
| Auth | `Authorization: Bearer <access token>` for native and automation clients; httpOnly session cookie + `X-CSRF-Token` for web. Deny by default: `assert_routes_authenticated()` at startup, exceptions only in `KEYLESS_ROUTES` |
| Authorization | Every resource resolves to a vault; caller needs `viewer` (read), `editor` (write) or `owner` (admin) on it. Unauthorized vaults return `404`, not `403`, to avoid leaking existence |
| Rate limits | Per principal and per IP; `429` with `Retry-After` and `RateLimit-*` headers |
| Limits | JSON body ≤ 1 MiB; note content ≤ 16 MiB; blob ≤ configurable (default 512 MiB), chunked above 8 MiB |
| Tracing | `X-Request-ID` accepted or generated, echoed, logged; W3C `traceparent` propagated |

## 2. Keyless routes

The complete initial `KEYLESS_ROUTES` list. Adding to it needs review.

| Route | Why |
|---|---|
| `GET /healthz` | Liveness probe |
| `GET /readyz` | Readiness probe: 200 `{"status": "ok"}` when PostgreSQL (`SELECT 1`) and Valkey (`PING`) answer and `vault_root` and `history_root` are writable directories, otherwise 503 `{"status": "fail"}`; no details in the body |
| `GET /api/v1/meta` | Server version, API and sync protocol versions, enabled login methods |
| `GET /api/v1/meta/path-rules` | Shared filename rules for clients |
| `GET /api/v1/auth/authorize`, `POST /api/v1/auth/token`, `GET /api/v1/auth/oidc/{provider}/callback`, `POST /api/v1/auth/login` | Login and token exchange (protected by PKCE, CSRF state and rate limits) |

## 3. Resources

### 3.1 Vault

```json
{
  "id": "0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c",
  "name": "Work",
  "role": "owner",
  "revision": 3,
  "created_at": "2026-10-17T10:30:00.000Z",
  "settings": { "sync_obsidian_config": false, "ai_enabled": false }
}
```

### 3.2 Note (metadata)

```json
{
  "id": "018f5a40-2d14-7b9c-8e3a-123456789abc",
  "vault_id": "0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c",
  "path": "Work/Projects/Project Architecture.md",
  "title": "Project Architecture",
  "revision": 42,
  "content_hash": "sha256:9f86d0…",
  "size": 2048,
  "created_at": "2026-10-17T10:30:00.000Z",
  "modified_at": "2026-10-17T11:45:00.000Z",
  "modified_by_device": "macbook-01",
  "tags": ["architecture", "development"],
  "aliases": ["Architecture Design"],
  "properties": { "opennote": { "favorite": true } },
  "frontmatter_error": null,
  "path_warning": null,
  "has_id_in_file": true
}
```

`title` = frontmatter `title` if present, else the file name without `.md`. `created_at`/`modified_at` come from revisions, not from frontmatter.

### 3.3 Note content

`GET /api/v1/notes/{id}/content` returns the exact bytes as `text/markdown` with `ETag`. `PUT` of the same path with `If-Match` replaces the bytes. The server never reformats content.

### 3.4 Attachment

`{ id, vault_id, path, revision, content_hash, size, media_type, created_at, modified_at }`. Bytes via `GET /api/v1/attachments/{id}/content` (supports `Range`). Uploaded `media_type` is sniffed server-side; the client-declared type is not trusted.

### 3.5 Tag

`{ name: "project/alpha", count: 12 }`. Tags are derived; there is no tag create endpoint. Renaming a tag is a bulk note edit (Phase 6).

## 4. Endpoints

Phase in brackets. All except `KEYLESS_ROUTES` require authentication.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/vaults` | List vaults the caller can access [2] |
| POST | `/api/v1/vaults` | Create a vault (empty, or register an existing directory under the server's vault root; admin only) [2] |
| GET / PATCH / DELETE | `/api/v1/vaults/{vault_id}` | Read, rename/settings, delete (soft; owner, `If-Match`) [2] |
| GET | `/api/v1/notes?vault_id=&folder=&tag=&cursor=&limit=&sort=` | List note metadata [2] |
| POST | `/api/v1/notes` | Create: `{ vault_id, path, content }` (content optional; OpenNote-created notes get `id` frontmatter) [2] |
| GET | `/api/v1/notes/{id}` | Metadata [2] |
| GET / PUT | `/api/v1/notes/{id}/content` | Read / replace bytes [2] |
| PATCH | `/api/v1/notes/{id}` | Move/rename `{ path }`, or metadata edit `{ tags?, aliases?, opennote? }` applied with the round-trip YAML editor [2] |
| DELETE | `/api/v1/notes/{id}` | Delete (tombstone + history) [2] |
| GET | `/api/v1/notes/{id}/links` | Outgoing, incoming (backlinks), unresolved [2 basic, 6 full] |
| GET | `/api/v1/notes/{id}/revisions`, `/revisions/{rev}`, `/revisions/{rev}/content` | History [5] |
| POST | `/api/v1/notes/{id}/restore` | Restore `{ from_revision }` [5] |
| GET | `/api/v1/folders?vault_id=` | Folder tree [2] |
| POST / PATCH / DELETE | `/api/v1/folders` | Create, move/rename (batch of file moves), delete (only empty, or recursive with `?recursive=true` producing tombstones) [2] |
| POST | `/api/v1/attachments` | Multipart upload `{ vault_id, path, file }` [2] |
| GET / DELETE | `/api/v1/attachments/{id}`, `/content` | [2] |
| GET | `/api/v1/tags?vault_id=` | Tag list with counts [2] |
| GET | `/api/v1/search?vault_id=&q=&cursor=&limit=` | Search, grammar in §5 [2] |
| GET / POST / DELETE | `/api/v1/saved-searches` | [6] |
| PUT / HEAD | `/api/v1/blobs/{sha256}` | Content-addressed upload / existence check for sync [5, prototype 1] |
| GET | `/api/v1/sync/{vault_id}/changes?cursor=` | Pull [5] |
| GET | `/api/v1/sync/{vault_id}/snapshot` | Full file list for reconcile [5] |
| POST | `/api/v1/sync/{vault_id}/push` | Push operations [5] |
| GET / POST / DELETE | `/api/v1/devices` | Device registration and revocation [2] |
| GET / PATCH | `/api/v1/conflicts?vault_id=`, `/conflicts/{id}` | List, mark resolved [5] |
| WS | `/api/v1/events` | Change hints `{ vault_id, seq }` for subscribed vaults [5] |
| GET / POST / DELETE | `/api/v1/tokens` | Personal access tokens [2] |
| GET | `/api/v1/me` | Current user, roles [2] |

The REST note endpoints and the sync endpoints share one commit path in the `sync` module; a `PUT` with `If-Match: "41"` behaves like a sync `update` with `base_revision = 41` except that it returns `412` instead of attempting a merge. Clients that want merge semantics use sync push.

## 5. Search query grammar (v1)

```ebnf
query      = ws, [ expr, { ws, expr } ], ws ;            (* implicit AND *)
expr       = term, { ws, "OR", ws, term } ;
term       = [ "-" ], ( group | filter | phrase | word ) ;   (* "-" negates *)
group      = "(", query, ")" ;
filter     = key, ":", value ;
key        = "tag" | "notebook" | "path" | "title" | "type" | "has"
           | "created" | "modified" | "before" | "after" | "is" ;
value      = phrase | word ;
phrase     = '"', { char - '"' | '\"' }, '"' ;
word       = char, { char } ;                            (* no whitespace, no unescaped ( ) " *)
```

| Filter | Meaning | Example |
|---|---|---|
| `tag:x` | Has tag `x` or a child tag `x/…` | `tag:project` |
| `notebook:x` | Under top-level folder `x` (alias `path:` for any folder prefix) | `notebook:Work` |
| `title:x` | Word/phrase in title | `title:"weekly sync"` |
| `type:x` | Attachment media type family (`pdf`, `image`, `audio`) | `type:pdf` |
| `has:x` | `attachment`, `task`, `link`, `unresolved` | `has:attachment` |
| `created:` / `modified:` | Date `YYYY-MM-DD` or range `YYYY-MM-DD..YYYY-MM-DD` | `created:2026-01-01` |
| `before:` / `after:` | Modified before/after date | `after:2026-09-01` |
| `is:x` | `favorite`, `archived`, `conflict` | `is:favorite` |

Free words and phrases match title, body, aliases, tags and (Phase 6) OCR text using PostgreSQL full-text search (`websearch`-style parsing done by our parser, `simple` + language configuration per vault) with trigram fallback for partial words. Unknown keys are treated as plain words, never as errors. Every query is scoped to the caller's authorized vaults before any matching.

## 6. Versioning and deprecation

`GET /api/v1/meta` returns `{ server_version, api_versions: ["v1"], sync_protocol_versions: [1], login_methods: [...] }`. Deprecated fields are announced in release notes, marked `deprecated: true` in OpenAPI and kept for at least two minor releases.
