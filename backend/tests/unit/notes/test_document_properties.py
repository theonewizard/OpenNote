"""Property test (testing strategy §3): an edit changes only the bytes of its span."""

from hypothesis import given, settings
from hypothesis import strategies as st

from app.notes.document import parse_note, replace_span

CONSTRUCTS = [
    "# Heading",
    "---",
    "...",
    "tags: [a, b]",
    "- [ ] task",
    "> [!note] callout",
    "[[Link|Alias]] and ![[image.png|300]]",
    "#tag #nested/tag",
    "%%comment%%",
    "$e^x$",
    "```",
    "| a | b |",
    "<div>html</div>",
    "trailing  ",
    "\ttab",
    "café naïve 日本語",
    "",
]


@st.composite
def markdown_documents(draw: st.DrawFn) -> bytes:
    lines = draw(st.lists(st.sampled_from(CONSTRUCTS) | st.text(max_size=20), max_size=30))
    endings = draw(st.sampled_from(["\n", "\r\n", "mixed"]))
    if endings == "mixed":
        text = "".join(line + draw(st.sampled_from(["\n", "\r\n"])) for line in lines)
    else:
        text = endings.join(lines) + draw(st.sampled_from(["", endings]))
    bom = b"\xef\xbb\xbf" if draw(st.booleans()) else b""
    return bom + text.encode("utf-8", "surrogatepass")


@settings(max_examples=400)
@given(raw=markdown_documents(), data=st.data())
def test_edit_changes_only_the_span(raw, data):
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return  # lone surrogates: not UTF-8, a read-only note
    doc = parse_note(raw)
    assert doc.raw == raw
    start = data.draw(st.integers(0, len(doc.text)))
    stop = data.draw(st.integers(start, len(doc.text)))
    new = data.draw(st.text(alphabet="ab\n", max_size=10))
    out = replace_span(doc, slice(start, stop), new)
    prefix = (b"\xef\xbb\xbf" if doc.bom else b"") + doc.text[:start].encode()
    assert out.startswith(prefix)
    assert out.endswith(doc.text[stop:].encode())
