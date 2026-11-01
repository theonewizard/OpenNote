# ADR-0005: Revision-based, server-authoritative synchronization

Status: Accepted (2026-11-01)  
Date: 2026-10-17  
Deciders: Flemming

## Context
Design §7 and §15.9 require revision preconditions, conflict preservation, tombstones, resumability and no reliance on timestamps; CRDTs are explicitly deferred.

## Decision
Per-file integer revisions, a per-vault gap-free change sequence, pull by cursor and push with base revision, idempotent operations keyed by client-generated IDs, content-addressed blobs, and **three-way merge performed only on the server** using the history store as merge base. Unsafe merges produce conflict copies, never conflict markers. Full specification: [sync protocol](../sync-protocol.md).

## Consequences
- Clients stay simple (no merge engine in Swift or TypeScript), satisfying §15.2.6 "avoid duplicating business rules".
- A client cannot merge while offline; it keeps editing its own copy and the merge happens at the next push. Acceptable for single-user multi-device use; real-time co-editing needs a later CRDT layer.
- Server must keep history for at least the tombstone window.

## Alternatives
CRDT (Automerge/Yjs) as foundation: rejected by design §7.2; also stores non-Markdown state. Last-writer-wins: violates "never silently overwrite".
