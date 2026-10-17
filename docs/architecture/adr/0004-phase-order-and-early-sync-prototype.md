# ADR-0004: Phase order and early sync prototype

Status: Proposed  
Date: 2026-10-17  
Deciders: Flemming (pending review)

## Context
Design §15.7 orders phases Foundation → Storage → API → Web → Apple → Sync. Design §18 prefers Storage → **sync prototype** → API → clients, because sync carries the greatest data-integrity risk.

## Decision
Keep the §15.7 phase order (it is written as instructions) and add roadmap item **P1-12 Sync protocol prototype** to the end of Phase 1: a server-side implementation of the [sync protocol](../sync-protocol.md) commit/merge/pull logic with a seeded multi-client simulation harness. Phase 2's API is built on that prototype's commit path, so every mutating endpoint already goes through revisions.

## Consequences
Protocol flaws surface before the API and clients depend on them. Phase 1 grows by about one week. Phase 5 becomes integration (clients, UI, attachments, history UI) rather than protocol invention.
