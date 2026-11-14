"""Link rewriting after a rename (P6-09)."""

import pytest

from app.notes.document import parse_note
from app.notes.rename import rewrite_links


def _rewrite(text, old, new, others=("Other.md",), from_path="Notes/From.md"):
    before = [from_path, old, *others]
    after = [from_path, new, *others]
    out = rewrite_links(parse_note(text.encode()), from_path, old, new, before, after)
    return None if out is None else out.decode()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("see [[Old]] now", "see [[New]] now"),
        ("![[Old#Head|alias]]", "![[New#Head|alias]]"),
        ("[[Old#^blk]] and [[old]]", "[[New#^blk]] and [[New]]"),
        ("[[Old.md]]", "[[New.md]]"),
        ("| [[Old\\|a]] |", "| [[New\\|a]] |"),
        ("[t](../Old.md#h)", "[t](../New.md#h)"),
    ],
)
def test_wiki_and_markdown_links(text, expected):
    assert _rewrite(text, "Old.md", "New.md") == expected


def test_paths_and_ambiguity():
    # A bare name that would resolve elsewhere after the move becomes the vault path.
    got = _rewrite("[[Old]]", "Old.md", "Archive/Other.md", others=("Other.md",))
    assert got == "[[Archive/Other]]"
    assert _rewrite("[[A/Old]]", "A/Old.md", "B/Old.md", others=()) == "[[B/Old]]"


def test_markdown_forms():
    assert _rewrite("[x](<../My Old.md>)", "My Old.md", "My New.md", others=()) == (
        "[x](<../My New.md>)"
    )
    assert _rewrite("[x](../My%20Old.md)", "My Old.md", "Sub/My New.md", others=()) == (
        "[x](../Sub/My%20New.md)"
    )
    assert _rewrite("[x](../Old.md)", "Old.md", "A B/New.md", others=()) == "[x](../A%20B/New.md)"


def test_keeps_everything_else():
    text = (
        "---\ntitle: [[Old]]\n---\r\n`[[Old]]` [[Other]] https://x/Old.md [w](https://e/Old.md)\r\n"
    )
    assert _rewrite(text, "Old.md", "New.md") is None
    mixed = "a [[Old]]\r\nb [[Other]]\n```\n[[Old]]\n```\n"
    assert _rewrite(mixed, "Old.md", "New.md") == mixed.replace("a [[Old]]", "a [[New]]")
