"""The search query grammar of API contract §5: never raises, unknown keys are words."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.search.grammar import (
    MAX_LENGTH,
    MAX_TERMS,
    And,
    Filter,
    Node,
    Not,
    Or,
    Phrase,
    Word,
    parse,
    render,
)


@pytest.mark.parametrize(
    ("query", "tree"),
    [
        ("tag:project", Filter("tag", "project")),
        ("notebook:Work", Filter("notebook", "Work")),
        ('title:"weekly sync"', Filter("title", "weekly sync", quoted=True)),
        ("type:pdf", Filter("type", "pdf")),
        ("has:attachment", Filter("has", "attachment")),
        ("created:2026-01-01", Filter("created", "2026-01-01")),
        ("created:2026-01-01..2026-02-01", Filter("created", "2026-01-01..2026-02-01")),
        ("after:2026-09-01", Filter("after", "2026-09-01")),
        ("is:favorite", Filter("is", "favorite")),
        ("alpha beta", And((Word("alpha"), Word("beta")))),
        ("alpha OR beta", Or((Word("alpha"), Word("beta")))),
        ("a b OR c", And((Word("a"), Or((Word("b"), Word("c")))))),
        ("a OR b OR c", Or((Word("a"), Word("b"), Word("c")))),
        ("-draft", Not(Word("draft"))),
        ("-tag:old", Not(Filter("tag", "old"))),
        ("(a b) OR c", Or((And((Word("a"), Word("b"))), Word("c")))),
        ("-(a OR b)", Not(Or((Word("a"), Word("b"))))),
        ('"exact phrase"', Phrase("exact phrase")),
        (r'"say \"hi\""', Phrase('say "hi"')),
        ("TAG:Project", Filter("tag", "Project")),
        ("path:Work/Projects", Filter("path", "Work/Projects")),
    ],
)
def test_contract_examples(query: str, tree: Node) -> None:
    assert parse(query) == tree


@pytest.mark.parametrize(
    ("query", "tree"),
    [
        ("color:red", Word("color:red")),
        ("http://example.com", Word("http://example.com")),
        ("tag:", Word("tag:")),
        ("type:spreadsheet", Word("type:spreadsheet")),
        ("has:everything", Word("has:everything")),
        ("is:pinned", Word("is:pinned")),
        ("created:yesterday", Word("created:yesterday")),
        ("created:2026-13-01", Word("created:2026-13-01")),
        ("created:2026-02-01..2026-01-01", Word("created:2026-02-01..2026-01-01")),
        ("before:2026-01-01..2026-02-01", Word("before:2026-01-01..2026-02-01")),
        ("or", Word("or")),
    ],
)
def test_unknown_keys_and_bad_values_are_words(query: str, tree: Node) -> None:
    assert parse(query) == tree


@pytest.mark.parametrize(
    ("query", "tree"),
    [
        ("", None),
        ("   ", None),
        ("()", None),
        ('""', None),
        ("(a", Word("a")),
        ("a)", Word("a")),
        (")(", None),
        ('"open phrase', Phrase("open phrase")),
        ("OR", Word("OR")),
        ("a OR", And((Word("a"), Word("OR")))),
        ("OR a", And((Word("OR"), Word("a")))),
        ("a OR OR b", And((Or((Word("a"), Word("OR"))), Word("b")))),
        ("-", Word("-")),
        ("a -", And((Word("a"), Word("-")))),
        ("--a", Word("a")),
        ("---a", Not(Word("a"))),
        ("-)", Word("-")),
        ('tag:"', Word('tag:""')),
        ("Color:red", Word("Color:red")),
        ("((((a))))", Word("a")),
    ],
)
def test_malformed_input_degrades_gracefully(query: str, tree: Node | None) -> None:
    assert parse(query) == tree


def test_length_and_term_count_are_capped() -> None:
    many = parse(" ".join(f"w{i}" for i in range(MAX_TERMS * 3)))
    assert isinstance(many, And) and len(many.children) == MAX_TERMS
    assert parse("x" * (MAX_LENGTH * 2)) == Word("x" * MAX_LENGTH)
    deep = parse("(" * 10_000 + "a" + ")" * 10_000)
    assert deep is None or isinstance(deep, Node)


@given(st.text(max_size=300))
def test_arbitrary_text_never_raises(query: str) -> None:
    tree = parse(query)
    if tree is not None:
        render(tree)


@given(st.text(alphabet='ab:-()" \\OR\ttag', max_size=60))
def test_grammar_characters_never_raise(query: str) -> None:
    parse(query)


# Round trip: rendering a well-formed tree and parsing it gives the same tree.

_plain = st.text(alphabet="abcxyzé0129._/", min_size=1, max_size=8).filter(
    lambda s: s != "OR" and not s.startswith("-")
)
_words = _plain.map(Word)
_phrases = st.text(alphabet="abc xyz'é-:()", min_size=1, max_size=12).filter(str.strip).map(Phrase)
_filters = st.one_of(
    st.builds(Filter, st.sampled_from(["tag", "notebook", "path", "title"]), _plain),
    st.builds(
        lambda k, v: Filter(k, v, quoted=True),
        st.sampled_from(["tag", "path", "title"]),
        st.text(alphabet="ab c:é", min_size=1, max_size=8).filter(str.strip),
    ),
    st.builds(Filter, st.just("type"), st.sampled_from(["pdf", "image", "audio", "video"])),
    st.builds(
        Filter, st.just("has"), st.sampled_from(["attachment", "link", "unresolved", "task"])
    ),
    st.builds(Filter, st.just("is"), st.sampled_from(["favorite", "archived", "conflict"])),
    st.builds(Filter, st.sampled_from(["created", "modified"]), st.just("2026-01-01..2026-03-31")),
    st.builds(Filter, st.sampled_from(["before", "after"]), st.just("2026-09-01")),
)


def _flat(kind: type[And] | type[Or], children: list[Node]) -> Node:
    out: list[Node] = []
    for child in children:
        out.extend(child.children if isinstance(child, kind) else (child,))
    return kind(tuple(out))


def _trees(leaves: st.SearchStrategy[Node]) -> st.SearchStrategy[Node]:
    return st.one_of(
        leaves.map(lambda n: n.child if isinstance(n, Not) else Not(n)),
        st.lists(leaves, min_size=2, max_size=3).map(lambda c: _flat(And, c)),
        st.lists(leaves, min_size=2, max_size=3).map(lambda c: _flat(Or, c)),
    )


_queries = st.recursive(st.one_of(_words, _phrases, _filters), _trees, max_leaves=10)


@given(_queries)
def test_render_then_parse_round_trips(tree: Node) -> None:
    assert parse(render(tree)) == tree
