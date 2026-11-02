"""Server-side three-way merge (sync protocol §6)."""

from hypothesis import given
from hypothesis import strategies as st

from app.sync.merge import conflict_copy_path, merge_note

BASE = b"---\ntitle: Plan\ntags: [a]\n---\none\ntwo\nthree\nfour\nfive\n"


def test_identical_sides_are_clean_with_theirs():
    result = merge_note(BASE, b"x\n", b"x\n")
    assert result.clean and result.data == b"x\n"


def test_one_sided_change_takes_that_side():
    assert merge_note(BASE, BASE, b"ours\n").data == b"ours\n"
    assert merge_note(BASE, b"theirs\n", BASE).data == b"theirs\n"


def test_non_overlapping_edits_merge():
    ours = BASE.replace(b"one\n", b"ONE\n")
    theirs = BASE.replace(b"five\n", b"FIVE\n")
    result = merge_note(BASE, theirs, ours)
    assert result.clean
    assert result.data == BASE.replace(b"one\n", b"ONE\n").replace(b"five\n", b"FIVE\n")


def test_title_and_cssclasses_change_merges_with_body_edit():
    ours = BASE.replace(b"title: Plan\n", b"title: Roadmap\ncssclasses: [wide]\n")
    theirs = BASE.replace(b"three\n", b"THREE\n")
    result = merge_note(BASE, theirs, ours)
    assert result.clean
    assert result.data == (
        b"---\ntitle: Roadmap\ntags: [a]\ncssclasses: [wide]\n---\none\ntwo\nTHREE\nfour\nfive\n"
    )


def test_overlapping_edits_conflict_without_markers():
    ours = BASE.replace(b"three\n", b"ours\n")
    theirs = BASE.replace(b"three\n", b"theirs\n")
    result = merge_note(BASE, theirs, ours)
    assert not result.clean and result.data is None
    for out in (ours, theirs):
        assert b"<<<<<<<" not in out


def test_frontmatter_key_merge():
    ours = BASE.replace(b"tags: [a]\n", b"tags: [a, b]\n")
    theirs = BASE.replace(b"---\none", b"aliases: [P]\n---\none")
    result = merge_note(BASE, theirs, ours)
    assert result.clean
    assert (
        result.data
        == b"---\ntitle: Plan\ntags: [a, b]\naliases: [P]\n---\none\ntwo\nthree\nfour\nfive\n"
    )


def test_key_deleted_on_one_side_is_deleted():
    ours = BASE.replace(b"title: Plan\n", b"")
    theirs = BASE.replace(b"one\n", b"1\n")
    assert (
        merge_note(BASE, theirs, ours).data == b"---\ntags: [a]\n---\n1\ntwo\nthree\nfour\nfive\n"
    )


def test_both_sides_change_same_key_conflict():
    ours = BASE.replace(b"title: Plan\n", b"title: Ours\n")
    theirs = BASE.replace(b"title: Plan\n", b"title: Theirs\n")
    assert not merge_note(BASE, theirs, ours).clean


def test_both_sides_same_key_same_value_is_clean():
    ours = BASE.replace(b"title: Plan\n", b"title: Same\n").replace(b"one\n", b"1\n")
    theirs = BASE.replace(b"title: Plan\n", b"title: Same\n")
    result = merge_note(BASE, theirs, ours)
    assert result.clean and b"title: Same\n" in result.data and b"\n1\n" in result.data


def test_invalid_yaml_merges_as_text():
    base = b"---\na: [\n---\nx\ny\nz\n"
    ours = base.replace(b"x\n", b"X\n")
    theirs = base.replace(b"z\n", b"Z\n")
    assert merge_note(base, theirs, ours).data == b"---\na: [\n---\nX\ny\nZ\n"


def test_crlf_preserved_in_merge():
    base = BASE.replace(b"\n", b"\r\n")
    ours = base.replace(b"one\r\n", b"ONE\r\n")
    theirs = base.replace(b"five\r\n", b"FIVE\r\n")
    result = merge_note(base, theirs, ours)
    assert result.clean and result.data == base.replace(b"one", b"ONE").replace(b"five", b"FIVE")


def test_line_endings_follow_theirs():
    ours = BASE.replace(b"one\n", b"ONE\n").replace(b"\n", b"\r\n")  # editor switched to CRLF
    theirs = BASE.replace(b"five\n", b"FIVE\n")
    result = merge_note(BASE, theirs, ours)
    assert result.clean and b"\r" not in result.data
    assert b"ONE\n" in result.data and b"FIVE\n" in result.data


def test_non_utf8_sides_only_merge_trivially():
    base, ours, theirs = b"caf\xe9\n", b"caf\xe9 1\n", b"caf\xe9 2\n"
    assert not merge_note(base, theirs, ours).clean
    assert merge_note(base, base, ours).data == ours


@given(
    n=st.integers(min_value=6, max_value=30),
    data=st.data(),
)
def test_disjoint_line_edits_always_merge(n, data):
    lines = [f"line {i}\n" for i in range(n)]
    a_start = data.draw(st.integers(0, n - 4))
    a_end = data.draw(st.integers(a_start + 1, n - 3))
    b_start = data.draw(st.integers(a_end + 1, n - 1))  # at least one untouched line between
    b_end = data.draw(st.integers(b_start + 1, n))
    a_new = data.draw(st.lists(st.text("xyz", min_size=1), min_size=0, max_size=3))
    b_new = data.draw(st.lists(st.text("uvw", min_size=1), min_size=0, max_size=3))
    a_lines = [f"A {t}\n" for t in a_new]
    b_lines = [f"B {t}\n" for t in b_new]
    base = "".join(lines).encode()
    ours = "".join(lines[:a_start] + a_lines + lines[a_end:]).encode()
    theirs = "".join(lines[:b_start] + b_lines + lines[b_end:]).encode()
    result = merge_note(base, theirs, ours)
    expected = lines[:a_start] + a_lines + lines[a_end:b_start] + b_lines + lines[b_end:]
    assert result.clean and result.data == "".join(expected).encode()


def test_conflict_copy_path():
    taken = {
        "Notes/Plan (conflict iPad 2026-11-01).md",
        "Notes/Plan (conflict iPad 2026-11-01) 2.md",
    }
    assert conflict_copy_path("Notes/Plan.md", "Mac", "2026-11-01", taken.__contains__) == (
        "Notes/Plan (conflict Mac 2026-11-01).md"
    )
    assert conflict_copy_path("Notes/Plan.md", "iPad", "2026-11-01", taken.__contains__) == (
        "Notes/Plan (conflict iPad 2026-11-01) 3.md"
    )
    assert conflict_copy_path("img.png", "a/b:c", "2026-11-01", lambda p: False) == (
        "img (conflict a-b-c 2026-11-01).png"
    )


def test_conflict_copy_path_is_always_a_valid_path():
    from app.vaults.paths import validate

    long_stem = "日" * 80
    for device in ("iPad #2 [old]|x", "Mac^", "tab\there"):
        path = conflict_copy_path(f"A/{long_stem}.md", device, "2026-11-01", lambda p: False)
        assert validate(path, note=True) == [], path
    first_taken = lambda p: p.endswith("2026-11-01).md")  # noqa: E731
    path = conflict_copy_path(f"A/{long_stem}.md", "Mac", "2026-11-01", first_taken)
    assert validate(path, note=True) == [] and path.endswith(" 2.md")
