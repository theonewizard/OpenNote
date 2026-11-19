# 2026-11-19 — Two migrations numbered 0009 on main

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Done in the "Build Phase 6 productivity features" thread; rulings continue its R-P6-0xx numbering.

## Prompts

- 2026-11-19 07:37 UTC, the coordinator (relaying the Phase 5 sync thread): main has two Alembic revisions `0009` with `down_revision` `0008` (`0009_link_lookup.py` from #56 and `0009_tasks.py` from #52); renumber `0009_tasks` to `0010`.

## Rulings

- R-P6-025: #56 and #52 both merged on 2026-11-19 with a migration whose revision ID is `0009`, so main had two revisions with the same ID and `alembic upgrade head` failed. The tasks migration merged second, so it moves: `0010_tasks.py`, revision `0010`, `down_revision` `0009` (the link lookup). The migration tests expect `0010 (head)`. A database that ran #52's tasks migration as `0009` exists only in development; such a database is dropped and rebuilt with `alembic upgrade head`.
