"""Extraction matches each corpus case's expected.json (testing strategy §3)."""

import dataclasses

import pytest

from app.notes.document import parse_note
from app.notes.extract import extract
from tests.compatibility.corpus import case_ids, corpus_cases

CASES = [c for c in corpus_cases() if "links" in c.expected]
pytestmark = pytest.mark.compatibility


def _as_dict(link):
    d = dataclasses.asdict(link)
    d.pop("embed")
    return d


@pytest.mark.parametrize("case", CASES, ids=case_ids(CASES))
def test_extraction_matches_expected(case):
    result = extract(parse_note(case.note_bytes()))
    assert [_as_dict(x) for x in result.links if not x.embed] == case.expected["links"]
    assert [_as_dict(x) for x in result.links if x.embed] == case.expected["embeds"]
    assert result.tags == case.expected["tags"]
    assert result.external_urls == case.expected["external_urls"]
