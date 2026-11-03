"""Round-trip frontmatter editing (storage contract §2.2): an edit changes only its key."""

import pytest

from app.notes.document import parse_note
from app.notes.frontmatter import (
    DELETE,
    FrontmatterInvalid,
    PropertyNotEditable,
    edit_properties,
    read_properties,
    splice_keys,
)
from tests.compatibility.corpus import case_ids, corpus_cases

VALID = corpus_cases(with_valid_frontmatter=True)
ALL = corpus_cases()


def _yaml_lines_without(raw: bytes, key: str) -> list[str]:
    """The frontmatter and body lines of `raw`, minus the lines of top-level `key`."""
    doc = parse_note(raw)
    assert doc.text is not None
    lines = doc.text.splitlines(keepends=True)
    out, skipping = [], False
    in_fm = doc.frontmatter is not None
    for index, line in enumerate(lines):
        if in_fm and index > 0 and line.rstrip("\r\n") in ("---", "..."):
            in_fm = False
        if in_fm and index > 0 and line[:1] not in (" ", "\t", "#", "\r", "\n", "-"):
            skipping = line.startswith(f"{key}:")
        if not (skipping and in_fm):
            out.append(line)
    return out


@pytest.mark.parametrize("case", ALL, ids=case_ids(ALL))
def test_corpus_frontmatter_matches_expected(case):
    props, error = read_properties(parse_note(case.note_bytes()))
    assert error is case.expected["frontmatter_error"]
    assert props == case.expected["frontmatter"]


@pytest.mark.parametrize("case", VALID, ids=case_ids(VALID))
def test_tag_edit_changes_only_the_tags_node(case):
    raw = case.note_bytes()
    out = edit_properties(parse_note(raw), {"tags": ["x", "y"]})
    assert read_properties(parse_note(out))[0]["tags"] == ["x", "y"]
    assert _yaml_lines_without(out, "tags") == _yaml_lines_without(raw, "tags")


def test_comments_and_quoting_of_other_keys_survive():
    head = b'---\n# keep me\ntitle: "Quoted: yes"   # and me\n'
    tail = b"other: 'single'\n---\nbody\n"
    out = edit_properties(parse_note(head + b"tags: [a]\n" + tail), {"tags": ["b"]})
    assert out == head + b"tags: [b]\n" + tail


def test_block_list_keeps_its_indentation():
    raw = b"---\ntags:\n  - a\n  - b\n---\n"
    assert edit_properties(parse_note(raw), {"tags": ["c"]}) == b"---\ntags:\n  - c\n---\n"


def test_crlf_frontmatter_edit_uses_crlf():
    raw = b"---\r\ntags:\r\n  - crlf\r\nx: 1\r\n---\r\nbody\r\n"
    out = edit_properties(parse_note(raw), {"tags": ["new"]})
    assert out == b"---\r\ntags:\r\n  - new\r\nx: 1\r\n---\r\nbody\r\n"


def test_new_key_appended_and_deleted_key_removed():
    raw = b"---\ntitle: t\n# between\ntags: [a]\n---\nbody\n"
    out = edit_properties(parse_note(raw), {"tags": DELETE, "aliases": ["A"]})
    assert out == b"---\ntitle: t\n# between\naliases:\n- A\n---\nbody\n"


def test_opennote_namespace_merged_key_by_key():
    raw = b"---\nopennote:\n  favorite: true\n  status: draft\n---\n"
    out = edit_properties(parse_note(raw), {"opennote": {"status": "done", "favorite": DELETE}})
    assert read_properties(parse_note(out))[0] == {"opennote": {"status": "done"}}


def test_note_without_frontmatter_gains_a_block_only_for_real_changes():
    raw = b"\xef\xbb\xbfbody\n"
    doc = parse_note(raw)
    assert edit_properties(doc, {"tags": DELETE}) == raw
    assert edit_properties(doc, {"tags": ["a"]}) == b"\xef\xbb\xbf---\ntags:\n- a\n---\nbody\n"


def test_invalid_yaml_refuses_edit_but_reads_body():
    doc = parse_note(b"---\na: [\n---\nbody\n")
    assert read_properties(doc) == (None, True)
    assert doc.text[doc.body] == "body\n"
    with pytest.raises(FrontmatterInvalid):
        edit_properties(doc, {"tags": ["x"]})


def test_duplicate_keys_are_invalid():
    assert read_properties(parse_note(b"---\ntags: a\ntags: b\n---\n")) == (None, True)


def test_non_mapping_frontmatter_is_invalid():
    assert read_properties(parse_note(b"---\n- a\n- b\n---\n")) == (None, True)


def test_created_and_modified_never_touched():
    raw = b"---\ncreated: 2024-01-02\nmodified: 2024-03-04\ntags: [a]\n---\n"
    out = edit_properties(parse_note(raw), {"tags": ["b"]})
    assert out == b"---\ncreated: 2024-01-02\nmodified: 2024-03-04\ntags: [b]\n---\n"


@pytest.mark.parametrize("key", ["title", "created", "modified", "cssclasses", "custom"])
def test_editing_other_top_level_key_refused(key):
    with pytest.raises(PropertyNotEditable):
        edit_properties(parse_note(b"---\na: 1\n---\n"), {key: "x"})


def test_splice_keys_writes_any_key_for_the_merge():
    out = splice_keys(parse_note(b"---\ntitle: a\ncssclasses: [w]\n---\n"), {"title": "b"})
    assert out == b"---\ntitle: b\ncssclasses: [w]\n---\n"
