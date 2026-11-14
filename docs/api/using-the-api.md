# Using the API

How to call the OpenNote v1 API from a script or another program (P8-07). The full reference is the OpenAPI document [openapi.json](openapi.json). Conventions, resources and the search grammar are in the [API contract](api-contract.md). The server does not serve interactive docs (`/docs` is 404). Load `openapi.json` into any OpenAPI viewer instead.

Every example uses `curl` and assumes `B=https://notes.example.org`, the URL of the web container or of the TLS proxy in front of it. The API is also reachable directly on the api container's port 8000.

## Signing in

Every route except the [keyless routes](api-contract.md#2-keyless-routes) needs one of these credentials. A request without one gets `401`.

| Credential | Header | For |
|---|---|---|
| Personal access token (PAT) | `X-API-Key: onp_…` | Scripts and automation. Limited to chosen vaults and to `read` or `write` |
| Device access token | `Authorization: Bearer …` | The native apps, from OAuth 2.0 code + PKCE (`/auth/authorize`, `/auth/token`) |
| Web session | cookies `opennote_session` and `opennote_csrf`, plus header `X-CSRF-Token` on writes | The web app. `POST /auth/login` sets them |

A PAT is what a script should use. To make one, sign in once with a password, then create the token:

```bash
# Sign in: the cookies go to a jar, the CSRF token comes back in the body
csrf=$(curl -s -c jar -H 'Content-Type: application/json' \
  -d '{"username": "alice", "password": "…"}' "$B/api/v1/auth/login" | jq -r .csrf_token)

# Find the vault, then create a token for it
vault=$(curl -s -b jar "$B/api/v1/vaults" | jq -r '.items[0].id')
curl -s -b jar -H "X-CSRF-Token: $csrf" -H 'Content-Type: application/json' \
  -d "{\"name\": \"backup script\", \"scope\": \"read\", \"vault_ids\": [\"$vault\"]}" \
  "$B/api/v1/tokens" | jq -r .secret
```

The secret (`onp_…`) is shown only once; the server keeps only its hash. Store it like a password. `scope` is `read` (viewer rights) or `write` (editor rights, in vaults where you are at least an editor); `expires_at` (RFC 3339) is optional. `GET /api/v1/tokens` lists your tokens without their secrets and `DELETE /api/v1/tokens/{id}` revokes one. A PAT is only accepted in `X-API-Key`, never as a Bearer token.

## Reading and writing notes

```bash
H="X-API-Key: $OPENNOTE_TOKEN"

curl -s -H "$H" "$B/api/v1/notes?vault_id=$vault"                 # first page of notes
curl -s -H "$H" "$B/api/v1/notes?vault_id=$vault&folder=Inbox"    # one folder
curl -s -H "$H" "$B/api/v1/search?q=tag:project%20budget"         # search (grammar: api-contract.md §5)
curl -s -H "$H" -D - "$B/api/v1/notes/$note/content"              # the exact bytes, with ETag: "<revision>"
```

Lists are paged with a cursor: when `next_cursor` is not null, pass it back as `cursor=…` for the next page.

Every write needs the revision you last read, as `If-Match`. That is how OpenNote avoids silently overwriting someone else's edit:

```bash
printf '# Hello\n\nWritten by a script.\n' |
  curl -s -X PUT -H "$H" -H 'If-Match: "1"' -H 'Content-Type: text/markdown' \
    --data-binary @- "$B/api/v1/notes/$note/content"
```

- `200` returns the note with its new revision in `ETag`.
- `412` means the note changed since you read it. The body's `current` holds its present state: read the content again, apply your change, and retry with the new revision.
- `428` means the `If-Match` header was missing.

`POST /api/v1/notes` with `{"vault_id": …, "path": "Inbox/Hello.md"}` creates a note and returns it with `ETag: "1"` and a `Location` header. The bytes you send are stored exactly as given: no reformatting, no added metadata. A new note gets an `id` in its frontmatter, and existing notes are never changed that way.

## Errors, limits and retries

- Errors are RFC 9457 problem details (`application/problem+json`) with `type`, `title`, `status`, `detail` and `instance`. They never contain stack traces or server paths. Send the `X-Request-ID` response header with a bug report.
- Rate limits are per credential and per client address, per minute (operator settings, defaults 600 and 1200, and 10 a minute for sign-in). Every response carries `RateLimit-Limit`, `RateLimit-Remaining` and `RateLimit-Reset`. Over a limit you get `429` with `Retry-After`: wait that many seconds.
- `POST` requests accept an `Idempotency-Key` header (a UUID). Sending the same key again replays the first answer instead of creating a second resource. `POST /tokens` is the exception, because it would have to store the secret.
- A vault or note you cannot see is a `404`, the same answer as one that does not exist.

## Generated clients

The web app's TypeScript client is generated from `openapi.json` (`scripts/gen-clients.sh`), and so is the Swift client in `apple/Packages/OpenNoteAPI`. Other languages can use any OpenAPI 3.1 generator on the same file. The file is checked against the server in CI, so it always matches the code on `main`.
