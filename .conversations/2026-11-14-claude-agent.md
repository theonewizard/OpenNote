# 2026-11-14 — Claude as an AI option: the vault assistant (part of P7-04)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Rulings continue the AI workstream's numbering in [2026-11-07-ai-provider-embeddings.md](2026-11-07-ai-provider-embeddings.md) (R-P7-009).

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-14 10:16 | Flemming (project chat) | "Add the option to add claude agent" |
| 2026-11-14 10:17 | Flemming (decision card, thread "Build optional AI backend") | Chose "Read and suggest" for "Choose how much the Claude agent may do in a vault" (other options: "Read and edit notes", "Claude provider only") |

## Rulings

- R-P7-010: "Claude agent" is read as a Claude-powered assistant over a vault with its own tools, built on the Claude API with a manual tool loop (official `anthropic` SDK, 2.8.0), not the Claude Agent SDK: the Agent SDK is Claude Code's harness with file, shell and web tools, which would reach far beyond one vault. The manual loop keeps every tool ours and scoped to one vault, and needs no beta tool runner.
- R-P7-011: read and suggest only (Flemming's card choice): tools `search_notes`, `read_note`, `suggest_edit`; nothing writes, which keeps ADR-0016 unchanged. A suggestion carries the revision and text Claude read, so a later "apply" can go through the normal conditional write and refuse a note that changed.
- R-P7-012: Claude is always external: it runs only for a vault with `enabled` and `allow_external`, and only when `OPENNOTE_AI_CLAUDE_API_KEY` (or its `_FILE`) is set. It is separate from `OPENNOTE_AI_PROVIDER` because Anthropic has no embeddings API.
- R-P7-013: model `claude-opus-5-5` by default (the current default Claude model; `OPENNOTE_AI_CLAUDE_MODEL` changes it, for example to `claude-sonnet-5-5`), effort `medium` set explicitly, server-side refusal fallback `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`), at most 12 model calls per question, 16,000 output tokens per call, 50,000 characters per note read.
- R-P7-014: entry point is `python -m app.ai ask` for now; an API route needs the OpenAPI document, clients and Zod schemas in the same change (CLAUDE.md §14) and a screen to be useful, so it is a follow-up.
- R-P7-015: `make constraints` also moved two unrelated transitive pins (annotated-doc, argon2-cffi-bindings); they were put back to keep the change surgical (CLAUDE.md §20). The new pins are anthropic's own dependencies.

## Output

Branch `feature/claude-agent`, based on `feature/ai-provider-embeddings` (pull request #37, not merged yet) with `main` merged in: `backend/app/ai/agent.py`, the Claude settings in `app/ai/config.py`, `python -m app.ai ask`, tests in `tests/integration/ai/test_agent.py` and `tests/unit/ai/test_config.py`, `anthropic==2.8.0` in requirements and constraints, [docs/deployment/ai.md](../docs/deployment/ai.md), versions.md and ROADMAP rows.
