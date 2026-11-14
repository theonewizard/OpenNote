"""Backlinks and the link graph read from the derived index (P6-08)."""

from pathlib import Path

from app.notes.graph import Edge, backlinks, graph
from app.notes.index import rebuild_index, remove_file
from app.notes.models import File
from app.vaults.registry import open_vault
from tests.integration.test_index_rebuild import add_files


def _vault(root: Path) -> None:
    root.mkdir()
    (root / "Hub.md").write_text("---\ntitle: The hub\n---\n[[#Top]] [[Hub]] # Top\n")
    (root / "A.md").write_text("[[Hub#Top|hub]] and [[hub]] and ![[pic.png]] [[Gone]] [[gone]]\n")
    (root / "B.md").write_text("[b](Hub.md) [[A]] ![[Hub]]\n")
    (root / "C.md").write_text("[[B]]\n")
    (root / "Orphan.md").write_text("alone\n")
    (root / "pic.png").write_bytes(b"\x89PNG\r\n")


def _setup(session, tmp_path):
    root = tmp_path / "v"
    _vault(root)
    vault_id = open_vault(session, root)
    ids = add_files(session, vault_id, root)
    rebuild_index(session, vault_id, root)
    return vault_id, {path: str(fid) for path, fid in ids.items()}, ids


def test_backlinks_list_other_notes_links_in_order(session, tmp_path):
    _, _, ids = _setup(session, tmp_path)
    got = [
        (b.path, b.title, b.ordinal, b.heading, b.alias, b.embed)
        for b in backlinks(session, ids["Hub.md"])
    ]
    assert got == [
        ("A.md", "A", 0, "Top", "hub", False),
        ("A.md", "A", 1, None, None, False),
        ("B.md", "B", 0, None, "b", False),
        ("B.md", "B", 2, None, None, True),
    ]
    assert backlinks(session, ids["Orphan.md"]) == []


def test_backlinks_skip_deleted_notes(session, tmp_path):
    _, _, ids = _setup(session, tmp_path)
    session.get(File, ids["B.md"]).deleted = True
    session.flush()
    assert {b.path for b in backlinks(session, ids["Hub.md"])} == {"A.md"}


def test_graph_has_every_note_and_counts_edges(session, tmp_path):
    vault_id, n, _ = _setup(session, tmp_path)
    g = graph(session, vault_id)
    assert [(x.kind, x.label) for x in g.nodes] == [
        ("note", "A"),
        ("note", "B"),
        ("note", "C"),
        ("note", "The hub"),
        ("note", "Orphan"),
    ]
    assert set(g.edges) == {
        Edge(n["A.md"], n["Hub.md"], 2),
        Edge(n["B.md"], n["Hub.md"], 2),
        Edge(n["B.md"], n["A.md"], 1),
        Edge(n["C.md"], n["B.md"], 1),
    }


def test_graph_toggles_add_attachments_and_unresolved_targets(session, tmp_path):
    vault_id, n, _ = _setup(session, tmp_path)
    g = graph(session, vault_id, attachments=True, unresolved=True)
    extra = [(x.id, x.kind, x.label) for x in g.nodes if x.kind != "note"]
    assert extra == [
        (n["pic.png"], "attachment", "pic.png"),
        ("unresolved:gone", "unresolved", "Gone"),
    ]
    assert Edge(n["A.md"], n["pic.png"], 1) in g.edges
    assert Edge(n["A.md"], "unresolved:gone", 2) in g.edges


def test_local_graph_walks_both_directions_to_depth(session, tmp_path):
    vault_id, n, ids = _setup(session, tmp_path)
    one = graph(session, vault_id, center=ids["C.md"])
    assert {x.path for x in one.nodes} == {"B.md", "C.md"}
    assert one.edges == [Edge(n["C.md"], n["B.md"], 1)]
    two = graph(session, vault_id, center=ids["C.md"], depth=2)
    assert {x.path for x in two.nodes} == {"A.md", "B.md", "C.md", "Hub.md"}
    assert len(two.edges) == 4  # A->Hub and B->Hub join once both ends are in


def test_graph_follows_index_updates(session, tmp_path):
    vault_id, n, ids = _setup(session, tmp_path)
    remove_file(session, ids["Hub.md"])
    session.get(File, ids["Hub.md"]).deleted = True
    session.flush()
    g = graph(session, vault_id, unresolved=True)
    assert n["Hub.md"] not in {x.id for x in g.nodes}
    assert Edge(n["A.md"], "unresolved:hub", 2) in g.edges
