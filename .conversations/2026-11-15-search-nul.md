# 2026-11-15 — Search query with NUL, flaky sync cursor test

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Done in the "Build Phase 6 productivity features" thread; rulings continue its R-P6-0xx numbering.

## Prompts

No new prompt. The backend job of PR #58 (run 43654837436, head 5c54835) went red on two failures in code already on `main`, which CI's instructions say to fix or explain.

## Rulings

- R-P6-022: `GET /api/v1/search` answered 500 when `q` held a NUL character: the words reach PostgreSQL as text (`ILIKE` patterns, `phraseto_tsquery`), and PostgreSQL text cannot hold NUL. Schemathesis generates NULs only now and then, so the contract test failed at random. The route now answers 422 (`invalid-query`) before parsing, like the request-body schemas' NUL rule; a regression test covers a word, a phrase and a filter.
- R-P6-023: `test_cursor_roundtrip_is_opaque` asserted that `"42"` is not in the base64 cursor, which random vault ids make true only most of the time. It now uses a twelve-digit sequence number, which cannot turn up by chance in practice. `app/sync/cursor.py` is unchanged.
