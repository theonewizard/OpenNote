# ADR-0015: Web client offline model: IndexedDB cache, not a vault

Status: Proposed  
Date: 2026-10-17  
Deciders: Flemming (pending review)

## Context
Design §16.C: browsers cannot hold an arbitrary local vault.

## Decision
The web app caches notes, bases, outbox and cursor in IndexedDB and runs the same sync protocol. It requests persistent storage and marks unsynced edits in the UI. It never claims to hold a vault; the File System Access API is not used in v1.

## Consequences
Honest offline story; eviction costs a re-download only, because unsynced outbox entries are kept in a persisted store and surfaced if lost.
