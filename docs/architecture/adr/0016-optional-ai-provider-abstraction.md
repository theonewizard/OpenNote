# ADR-0016: Optional AI behind a typed provider interface

Status: Accepted (2026-11-01)  
Date: 2026-10-17  
Deciders: Flemming

## Context
Design §9 and §15.12: AI optional, off by default, local first, provider-agnostic, cited answers, injection resistance, no unapproved edits.

## Decision
`backend/app/ai/` defines typed request/response models and one `AIProvider` protocol (`generate`, `embed`, `transcribe`), with implementations for Ollama, an OpenAI-compatible HTTP endpoint (covers llama.cpp server and opt-in external providers) and faster-whisper. Enabled per vault; external providers additionally need an explicit per-vault opt-in. AI results are suggestions the user applies; AI never writes to the vault itself. Retrieved note text is passed as delimited data with a fixed system prompt; answers must carry note IDs as citations, and uncited answers are flagged.

## Consequences
Phase 7 only. Nothing before Phase 7 imports `app.ai`, so the core works with the AI image absent.
