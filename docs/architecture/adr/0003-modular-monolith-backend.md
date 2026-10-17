# ADR-0003: Modular monolith backend

Status: Proposed  
Date: 2026-10-17  
Deciders: Flemming (pending review)

## Context
Design §6.1 says "initially deploy a collection of independent microservices", while §15.2.7 and §16 mandate a modular monolith and say to avoid premature microservices. `claude.md` §23 forbids distributed components when a local component suffices.

## Decision
One Python codebase (`backend/app`) with explicit module boundaries (vaults, notes, attachments, sync, search, auth, later tasks/calendar/ai). One container image runs as three process types: `api` (uvicorn), `worker` (background jobs), and, when AI is enabled, `ai` (separate image because of model runtime size). Modules talk through service functions, never through each other's tables.

## Consequences
Single deployable, single migration history, transactions across modules where sync needs them: a revision and its change-log entry commit in one PostgreSQL transaction ([sync protocol §2.3](../sync-protocol.md#23-commit-procedure)). Derived indexes (full-text, tags, links, later embeddings) are updated asynchronously by the worker, so search is eventually consistent: a note is readable by ID and listed immediately after a write, and appears in search results once the worker has indexed it (target under 5 seconds). Extraction of a module later remains possible because boundaries are explicit.

## Alternatives
Microservices per §6.1: more network failure modes and distributed transactions around the sync commit path, which is the highest-risk area.
