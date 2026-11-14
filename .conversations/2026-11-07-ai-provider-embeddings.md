# 2026-11-07 — Optional AI backend: provider interface and embeddings (P7-01, P7-02)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Rulings are prefixed per workstream (R-P7-nnn) because several threads now work in parallel.

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-07 15:01 | Flemming (project chat) | "Run most of the phases in parallel so it is developed quickly." |
| 2026-11-07 20:27 | Phase 2 thread | Phase 2 merged first (main 56ed844): renumber to 0008 on 0007, and add the `embed_vault_job` call after a successful commit in `backend/app/api/deps.py` |
| 2026-11-07 15:03 | Coordinator (thread brief) | Workstream 5, low priority: P7-01 provider abstraction and P7-02 embeddings in the isolated `backend/app/ai` module; AI off by default, local first, external providers opt-in; no paid API usage without approval |

## Rulings

- R-P7-001: HTTP through the standard library (`urllib.request`), not a new dependency. Providers run in worker jobs, which are synchronous, so an async client buys nothing; `httpx2` is only a development dependency. Cost if wrong: one module to port.
- R-P7-002: the protocol has `embed` and `generate`; `transcribe` and faster-whisper (a large native dependency) wait for P7-07, the first feature that uses them (CLAUDE.md §20, §23).
- R-P7-003: "external" is decided from the base URL's host (loopback, private, link-local, dotless or private-DNS names are local; everything else external), so a misconfigured public host is treated as external and needs the vault's opt-in. Cost if wrong: a vault owner must opt in for a host that was in fact local.
- R-P7-004: the per-vault switch (`enabled`, `allow_external`) is a database table, not `.opennote/config.json`: vault files sync and travel, and must not be able to opt a vault into sending notes to an external provider.
- R-P7-005: embeddings reconcile against `files.content_hash` instead of hooking the commit path, which belongs to the Phase 2 and sync-server threads. A run embeds only changed notes and, inside them, only changed chunks; the enqueue after a commit is one line for whoever owns the committer process.
- R-P7-006: the `vector` column has no fixed dimension (the dimension is the model's); the similarity index is P7-03's decision. A model change re-embeds everything.
- R-P7-007: no HTTP route in this change: the vault switch is the `python -m app.ai` command until the API's AI settings exist, so the OpenAPI document and clients are untouched (CLAUDE.md §14), avoiding a collision with Phase 2's contract pull request.
- R-P7-008: migration `0006` (three new tables, no change to existing ones). If another branch lands a `0006` first, this one is renumbered onto the new head before merge. Phase 2 (pull request #42, main 56ed844) landed `0006` and `0007` first, so it is `0008`, revising `0007`.
- R-P7-009: the re-embed hook sits in `app.api.deps.commit`, as the Phase 2 thread proposed, and goes through `app.ai.notify.request_embedding`, which builds the Dramatiq message by actor name on a broker of its own: importing `app.ai.jobs` in the API would bind the actor to Dramatiq's global broker, which the API never configures. It enqueues only when a provider is set, after the vault lock is released, and swallows broker errors so AI can never fail a save; the job checks the vault's opt-in.

## Output

Branch `feature/ai-provider-embeddings` in `.worktrees/ai/`: `backend/app/ai/` (config, providers, models, embeddings, jobs, CLI), migration `0008_ai.py`, the hook in `app/api/deps.py`, the worker's job list, tests under `tests/unit/ai` and `tests/integration/ai`, [docs/deployment/ai.md](../docs/deployment/ai.md), ROADMAP and status rows.
