"""Chunking: paragraphs joined up to the limit, a new chunk at every heading."""

from app.ai.embeddings import chunk_text


def test_short_paragraphs_share_a_chunk():
    assert chunk_text("one\n\ntwo\r\n\r\nthree\n") == ["one\n\ntwo\n\nthree"]


def test_a_heading_starts_a_new_chunk_but_a_tag_does_not():
    body = "intro\n\n# Goals\nship\n\n#tag line\n\n## Risks\nnone"
    assert chunk_text(body) == ["intro", "# Goals\nship\n\n#tag line", "## Risks\nnone"]


def test_chunks_stay_within_the_limit():
    body = "\n\n".join(["a" * 6] * 5)
    assert chunk_text(body, max_chars=14) == ["aaaaaa\n\naaaaaa", "aaaaaa\n\naaaaaa", "aaaaaa"]


def test_a_long_paragraph_is_cut():
    assert chunk_text("x" * 25, max_chars=10) == ["x" * 10, "x" * 10, "x" * 5]


def test_an_empty_body_has_no_chunks():
    assert chunk_text("\n \n\n") == []
