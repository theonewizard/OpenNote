# ADR-0009: Background jobs on a Redis-protocol queue, Valkey server

Status: Proposed  
Date: 2026-10-17  
Deciders: Flemming (pending review)

## Context
Design §15.3 asks for Redis-backed background jobs. Redis changed licence in 2024 (RSALv2/SSPL, later adding AGPLv3 for Redis 8). Valkey is the BSD-licensed Linux Foundation fork and speaks the same protocol. `claude.md` §20 prefers established, well-maintained dependencies.

## Decision
- Queue library: **Dramatiq** with its Redis broker (mature, synchronous workers suit file and CPU-bound jobs, retries with backoff and dead-letter built in). Phase 0 Task 1 re-checks maintenance status before pinning.
- Server: **Valkey** by default; any Redis-protocol server works. Also used for WebSocket fan-out (pub/sub) across API replicas.
- Valkey is not authoritative for anything: jobs are re-derivable (indexing is idempotent and reconciliation re-enqueues).

## Consequences
Licence-clean default; Flemming can point at an existing Redis. Losing the queue loses only pending derived work.

## Alternatives
Celery (heavier, more configuration), RQ (fewer reliability features), arq/SAQ (async-only, smaller communities), PostgreSQL-based queue (fewer moving parts; worth revisiting if Valkey turns out to be the only reason for an extra service — noted for the ponytail review).
