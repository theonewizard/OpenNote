# ADR-0003: Modular monolith backend

Status: Proposed  
Date: 2026-10-17  
Deciders: Flemming (pending review)

## Context
Design §6.1 says "initially deploy a collection of independent microservices", while §15.2.7 and §16 mandate a modular monolith and say to avoid premature microservices. `claude.md` §23 forbids distributed components when a local component suffices.

## Decision
One Python codebase (`backend/app`) with explicit module boundaries (vaults, notes, attachments, sync, search, auth, later tasks/calendar/ai). One container image runs as three process types: `api` (uvicorn), `worker` (background jobs), and, when AI is enabled, `ai` (separate image because of model runtime size). Modules talk through service functions, never through each other's tables.

## Consequences
Single deployable, single migration history, transactions across modules where sync needs them (commit revision + index update + change log). Extraction of a module later remains possible because boundaries are explicit.

## Alternatives
Microservices per §6.1: more network failure modes and distributed transactions around the sync commit path, which is the highest-risk area.
