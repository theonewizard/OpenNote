"""ENEX reading, ENML to Markdown and safe file names (P6-10)."""

import io

import pytest

from app.imports.enex import EnexError, read_enex, safe_name, to_markdown


def _md(enml: str, media=None) -> str:
    return to_markdown(f"<en-note>{enml}</en-note>", media or {})


@pytest.mark.parametrize(
    ("enml", "expected"),
    [
        (
            "<h2>Head</h2><div>Body <b>bold</b> <i>it</i> <s>gone</s></div>",
            "## Head\n\nBody **bold** *it* ~~gone~~\n",
        ),
        (
            "<div><en-todo checked='true'/>done</div><div><en-todo/>open</div>",
            "- [x] done\n- [ ] open\n",
        ),
        ("<ul><li><en-todo/>in a list</li></ul>", "- [ ] in a list\n"),
        (
            "<ul><li>a<ul><li>b</li></ul></li></ul><ol><li>x</li><li>y</li></ol>",
            "- a\n  - b\n1. x\n2. y\n",
        ),
        ("<div>a<br/>b</div>", "a\nb\n"),
        ("<a href='https://e.org'>site</a>", "[site](https://e.org)\n"),
        ("<pre>if a &lt; b:\n    go()</pre>", "```\nif a < b:\n    go()\n```\n"),
        (
            "<div style='-en-codeblock: true'><div>one</div><div>  two</div></div>",
            "```\none\n  two\n```\n",
        ),
        ("<blockquote><div>q1</div><div>q2</div></blockquote>", "> q1\n\n> q2\n"),
        (
            "<table><tr><th>h</th><th>i</th></tr><tr><td>1|2</td></tr></table>",
            "| h | i |\n| --- | --- |\n| 1\\|2 |  |\n",
        ),
        ("<hr/><en-crypt cipher='AES'>abc</en-crypt>", "---\n\n`[encrypted]`\n"),
        ("<en-media hash='ABC' type='image/png'/><en-media hash='zzz'/>", "![[R/pic.png]]\n"),
        ("<style>x{}</style><div>  spaced   out  </div>", "spaced out\n"),
        ("", ""),
    ],
)
def test_to_markdown(enml, expected):
    assert _md(enml, {"abc": "R/pic.png"}) == expected


def test_read_enex():
    data = (
        b"<en-export><note><title> T </title><content>&lt;en-note/&gt;</content>"
        b"<created>bad</created><updated>20260101T000000Z</updated><tag> a </tag><tag/>"
        b"<resource><data>!!notbase64</data></resource>"
        b"<resource><data>aGk=</data><mime>text/plain</mime></resource></note></en-export>"
    )
    [note] = read_enex(io.BytesIO(data))
    assert (note.title, note.created, note.updated.year, note.tags) == ("T", None, 2026, ["a"])
    [res] = note.resources
    assert (res.data, res.file_name) == (b"hi", "attachment-2.txt")


def test_read_enex_refuses_broken_xml():
    with pytest.raises(EnexError):
        list(read_enex(io.BytesIO(b"<en-export><note>")))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Plan: A/B #1 [x]", "Plan A B 1 x"),
        ("  .hidden. ", "hidden"),
        ("CON", "fallback"),
        ("nul.txt", "fallback"),
        ("\x00\x01", "fallback"),
        ("é" * 300, "é" * 100),
    ],
)
def test_safe_name(name, expected):
    assert safe_name(name, "fallback") == expected
