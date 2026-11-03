"""Every corpus note reads and writes back byte for byte (storage contract §2.1)."""

import pytest

from app.notes.document import parse_note, replace_span
from tests.compatibility.corpus import case_ids, corpus_cases

CASES = corpus_cases()
pytestmark = pytest.mark.compatibility


def test_corpus_is_present():
    assert len(CASES) >= 25


@pytest.mark.parametrize("case", CASES, ids=case_ids(CASES))
def test_corpus_roundtrip_is_byte_identical(case):
    raw = case.note_bytes()
    assert parse_note(raw).raw == raw


@pytest.mark.parametrize("case", CASES, ids=case_ids(CASES))
def test_identity_edit_is_byte_identical(case):
    doc = parse_note(case.note_bytes())
    if doc.text is None:
        pytest.skip("read-only note")
    assert replace_span(doc, doc.body, doc.text[doc.body]) == doc.raw


def test_ten_megabyte_note_roundtrips():
    raw = (b"- line of a large note\n" * 460_000)[: 10 * 1024 * 1024]
    doc = parse_note(raw)
    assert doc.raw == raw and replace_span(doc, doc.body, doc.text[doc.body]) == raw
