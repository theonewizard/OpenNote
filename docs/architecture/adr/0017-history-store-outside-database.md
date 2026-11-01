# ADR-0017: Revision history in a content-addressed store outside PostgreSQL

Status: Accepted (2026-11-01)  
Date: 2026-10-17  
Deciders: Flemming

## Context
Design §10.4: version history must not depend solely on database backups. Sync merges need old revisions as merge bases.

## Decision
Store every revision's bytes zstd-compressed and content-addressed under `<history_root>/<vault_id>/objects/`, with an append-only monthly JSONL log of revision metadata next to it. PostgreSQL holds the same metadata for queries and is rebuildable from the log. Retention per decision D6, enforced by a worker job that never deletes the newest revision of any file or any revision referenced by an open conflict.

## Consequences
The write order and crash recovery that keep the log complete for every acknowledged revision are defined in [sync protocol §2.3](../sync-protocol.md#23-commit-procedure).

History survives a database loss; backups are plain files (rsync/restic friendly). Storage grows with edit volume; deduplication and compression keep it modest for text.
