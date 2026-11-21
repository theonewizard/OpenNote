# Search benchmark regression from OCR attachment matching (2026-11-21)

Thread: Fix failing checks and conflicts on open PRs. Requested by Flemming.

## Prompts

- After all PRs were merged, the nightly `benchmark-nightly` job on main was found red since 2026-11-19 (search p95 1,449 ms against the 500 ms target on 2026-11-21; p50 288 ms, up from 46 ms). Flemming chose "Investigate here" on the decision card.

## Findings

- Reproduced with `pytest -m slow tests/integration/api/test_search_perf.py` (100k notes written into the tables): p95 925 ms. With the OCR clause removed: 184 ms.
- Cause: P6-06 (#67) added `_attachment_text`, a correlated `EXISTS` (note_links → files → ocr_texts) OR-ed with the full-text and trigram matches. The planner can no longer drive the OR from the indexes and evaluates the subquery per search document.

## Output

- `backend/app/search/query.py`: the attachment match is one uncorrelated subquery collected with `ARRAY(...)` and tested as `file_id = ANY(...)`. `ARRAY()` of no rows is an empty array (never NULL), so negated terms behave as before. The outer WHERE still applies the vault scope.
- Verified: search_perf p95 202 ms; OCR integration tests 9/9 (with Tesseract 5.3.4 installed locally); full backend suite 1112 passed, 6 skipped; ruff, mypy clean. The real-vault 100k benchmark (`test_vault_perf.py`, ~40 min) is left to the nightly job.
