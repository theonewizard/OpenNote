"""The byte-preserving note model (storage contract §2.1, §2.2)."""

import pytest

from app.notes.document import ReadOnlyNote, parse_note, replace_span, with_newlines


def test_crlf_note_edit_keeps_crlf():
    doc = parse_note(b"---\r\ntitle: a\r\n---\r\nline\r\n")
    new = with_newlines("x\ny\n", doc.newline)
    assert replace_span(doc, doc.body, new) == b"---\r\ntitle: a\r\n---\r\nx\r\ny\r\n"


def test_bom_kept_and_frontmatter_found_after_bom():
    doc = parse_note(b"\xef\xbb\xbf---\ntags: [a]\n---\nbody\n")
    assert doc.bom and doc.text[doc.frontmatter] == "tags: [a]\n"
    assert replace_span(doc, doc.body, "new\n") == b"\xef\xbb\xbf---\ntags: [a]\n---\nnew\n"


def test_frontmatter_and_body_spans():
    doc = parse_note(b"---\na: 1\n...\nbody\n")
    assert doc.text[doc.frontmatter] == "a: 1\n" and doc.text[doc.body] == "body\n"


def test_empty_frontmatter_block():
    doc = parse_note(b"---\n---\nbody\n")
    assert doc.frontmatter is not None and doc.text[doc.frontmatter] == ""


@pytest.mark.parametrize(
    "raw",
    [b"\n---\na: 1\n---\n", b"---\na: 1\nno close\n", b"--- \na: 1\n---\n", b"text\n"],
)
def test_no_frontmatter_means_whole_file_is_body(raw):
    doc = parse_note(raw)
    assert doc.frontmatter is None and doc.text[doc.body] == raw.decode()


def test_closing_delimiter_at_end_without_newline():
    doc = parse_note(b"---\na: 1\n---")
    assert doc.text[doc.frontmatter] == "a: 1\n" and doc.text[doc.body] == ""


def test_windows_1252_note_is_read_only():
    doc = parse_note("café".encode("cp1252"))
    assert doc.text is None
    with pytest.raises(ReadOnlyNote):
        replace_span(doc, doc.body, "x")


def test_no_trailing_newline_preserved():
    doc = parse_note(b"a\nb")
    assert replace_span(doc, slice(0, 1), "z") == b"z\nb"


@pytest.mark.parametrize(
    ("raw", "newline"),
    [(b"a\r\nb\r\nc\n", "\r\n"), (b"a\nb\r\nc\n", "\n"), (b"no newline", "\n"), (b"", "\n")],
)
def test_dominant_newline(raw, newline):
    assert parse_note(raw).newline == newline


def test_replacement_is_verbatim_so_mixed_endings_survive():
    doc = parse_note(b"a\r\nb\nc\n")
    assert replace_span(doc, slice(0, 1), "z") == b"z\r\nb\nc\n"
    assert replace_span(doc, doc.body, doc.text) == doc.raw


def test_with_newlines_converts_every_ending():
    assert with_newlines("a\nb\r\nc", "\r\n") == "a\r\nb\r\nc"
    assert with_newlines("a\r\nb\n", "\n") == "a\nb\n"
