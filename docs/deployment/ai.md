# Optional AI

AI is off unless two things are true: the server names a provider (`OPENNOTE_AI_PROVIDER`), and the vault has AI switched on. A provider outside the local network additionally needs the vault's `allow_external` opt-in ([ADR-0016](../architecture/adr/0016-optional-ai-provider-abstraction.md)). With AI off, nothing calls a provider and the rest of OpenNote works as before.

What exists today (P7-01, P7-02): the provider interface and the embedding pipeline in the worker. Semantic search, the assistant, tagging, summaries and transcription are later items ([ROADMAP.md, Phase 7](../ROADMAP.md#phase-7--ai-m7)).

## Server settings

Read by the worker and by `python -m app.ai`; the API reads `OPENNOTE_AI_PROVIDER` only, to decide whether a save enqueues an embedding run, so set it there too.

| Variable | Form |
|---|---|
| `OPENNOTE_AI_PROVIDER` | `none` (default), `ollama`, or `openai` for any OpenAI-compatible endpoint (llama.cpp server, vLLM, an external provider) |
| `OPENNOTE_AI_BASE_URL` | required with a provider. Ollama: `http://ollama:11434`. OpenAI-compatible: the URL up to and including `/v1`, such as `http://llama:8080/v1` |
| `OPENNOTE_AI_EMBED_MODEL` | the embedding model, such as `nomic-embed-text`; without it nothing is embedded |
| `OPENNOTE_AI_CHAT_MODEL` | the chat model for later features |
| `OPENNOTE_AI_API_KEY` | optional bearer token; a secret, so prefer `OPENNOTE_AI_API_KEY_FILE` |
| `OPENNOTE_AI_TIMEOUT_SECONDS` | per request, default `60`, at most `600` |

**Local or external.** The provider counts as local when the host in `OPENNOTE_AI_BASE_URL` is a loopback, private (RFC 1918, unique-local) or link-local address, a name without a dot (a Compose service), or a name ending in `.local`, `.lan`, `.internal`, `.localhost`, `.svc` or `.svc.cluster.local`. Every other host, any public name included, is external. The rule looks at the name only; a public name that happens to resolve to a private address still counts as external, which errs on the side of not sending notes.

Requests never follow redirects (a redirect would carry the API key elsewhere), responses are capped at 32 MiB and checked before use, and errors in the logs name the provider and the HTTP status, never the URL, the key or note text.

## Switching AI on for a vault

The per-vault switch lives in the database (`ai_vault_settings`), not in the vault, so copying or syncing a vault never turns AI on by itself.

```bash
python -m app.ai enable <vault-id>                    # local providers only
python -m app.ai enable <vault-id> --allow-external   # also an external provider
python -m app.ai embed <vault-id>                     # embed now, in this process
python -m app.ai disable <vault-id>                   # off, and drops the vault's embeddings
```

They read the same `OPENNOTE_*` settings as the worker. An API for this comes with the AI settings screen.

## Embeddings

A note's body (frontmatter left out) is cut into chunks of at most 2,000 characters: paragraphs are joined, and every Markdown heading starts a new chunk. Each chunk is embedded with the note's title in front and stored in `ai_chunks` as a pgvector `vector` with the model's dimension; `ai_note_state` records which file content and model the chunks came from. A run embeds only notes whose content or model changed, and within a changed note only chunks whose text changed. Deleted notes lose their chunks on the next run. Notes that are not valid UTF-8 get no chunks.

The worker job `embed_vault_job(<vault-id>)` runs one vault at a time (a PostgreSQL advisory lock); a message that finds the vault busy comes back 30 seconds later. A provider that is down fails the job, which Dramatiq retries three times with backoff. Every note, folder or attachment change committed through the API enqueues the job for its vault (`app.ai.notify`, called from `app.api.deps.commit`), but only when `OPENNOTE_AI_PROVIDER` is set; if Valkey is unreachable the save still succeeds and the next one asks again. Changes the API did not make (a file edited on the server's disk) are picked up by the next run, or by `python -m app.ai embed`.

The similarity index arrives with semantic search (P7-03): an index needs a fixed dimension, which depends on the model chosen.
