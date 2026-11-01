# ADR-0015: Web client offline model: IndexedDB cache, not a vault

Status: Accepted (2026-11-01)  
Date: 2026-10-17  
Deciders: Flemming

## Context
Design §16.C: browsers cannot hold an arbitrary local vault.

## Decision
The web app caches notes, bases, outbox and cursor in IndexedDB and runs the same sync protocol. It requests persistent storage and marks unsynced edits in the UI. It never claims to hold a vault; the File System Access API is not used in v1.

Cache records are namespaced by authenticated user ID and vault ID (one IndexedDB database per user). Every read checks the current session's user against the namespace. On logout or account switch the previous user's cache is closed and made unreadable to the new session; cached notes are deleted, but a non-empty outbox is never deleted silently: the user is told that unsynced edits exist and can sync them by signing back in or explicitly discard them.

## Consequences
Honest offline story. Evicting cached notes costs only a re-download, since the server holds them. Losing outbox entries is different: an edit that never reached the server is gone for good. To make that unlikely, the outbox lives in a separate store protected by `navigator.storage.persist()`, unsynced edits are shown in the UI, and the client syncs as soon as it is online. If the browser denies persistent storage, the UI warns that offline edits are at risk.
