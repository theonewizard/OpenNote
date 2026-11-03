"""Link, embed and tag extraction rules (storage contract §2.3)."""

from app.notes.document import parse_note
from app.notes.extract import extract


def _x(text: str):
    return extract(parse_note(text.encode()))


def test_links_in_code_not_extracted():
    result = _x("`[[a]]`\n\n```md\n[[b]] #c\n```\n[[d]]\n")
    assert [link.target for link in result.links] == ["d"] and result.tags == []


def test_url_fragment_is_not_a_tag():
    assert _x("see https://example.com/#frag and x#y\n").tags == []


def test_numeric_only_is_not_a_tag():
    assert _x("#123 #1a\n").tags == ["1a"]


def test_frontmatter_is_not_extracted():
    assert _x("---\ntags: [#a]\nlink: '[[X]]'\n---\n#b\n").tags == ["b"]
    assert _x("---\nlink: '[[X]]'\n---\nbody\n").links == []


def test_obsidian_comment_spanning_lines_hides_links():
    assert _x("%%\n[[Hidden]]\n%%\n[[Shown]]\n").links[0].target == "Shown"


def test_read_only_note_extracts_nothing():
    result = extract(parse_note("[[a]] #b".encode("cp1252") + b"\xe9"))
    assert result.links == [] and result.tags == []
