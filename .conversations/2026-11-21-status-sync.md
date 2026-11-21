# 2026-11-21 Sync the status docs with main

Thread: Sync implementation status with main. Requested by Flemming.

## Prompt

- Flemming: "sync the implementation plan and make a not in memory to update in when fixing tasks."

## What was done

- Built on #93 (branch `docs/status-after-search-fix`, which added PR numbers to rows for work merged 2026-11-19..21) so the two do not conflict.
- Checked every roadmap row against the merged pull requests (#1 to #92) and `main` at `031f516`, and against the code where a row claimed work that has no PR (grep of `web/src`, `apple/`, `backend/app`).
- docs/IMPLEMENTATION_STATUS.md: "Current phase" now describes Phases 3 to 8 running in parallel and Phase 2 as completed; completed rows moved out of "In progress"; P8-08 added; stale branch names, test counts and "Next planned work" replaced.
- docs/ROADMAP.md: COMPLETED with evidence: P0-09 (#3 green), P2-01 to P2-10 (#42; search p95 393 ms at 100k notes), P5-01 (#55), P5-02 (#62), P5-07 (#63, `tests/integration/sync/test_retention.py`), P8-04 (#40, restore drill green in `containers`). Corrected to NOT_STARTED because nothing is on `main`: P3-01, P3-03, P3-05, P3-06, P3-07, P3-09, P4-03, P6-07. Other rows got their PR numbers.
- The standing rule (every task PR updates both files) is in project memory and at the end of IMPLEMENTATION_STATUS.md.
