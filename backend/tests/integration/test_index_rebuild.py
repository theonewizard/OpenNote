"""The note index: derived from the vault, rebuildable, never touching `files` identity."""

import uuid
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.notes.index import index_file, rebuild_index
from app.notes.models import File, Note
from app.vaults.paths import casefold_key
from app.vaults.registry import open_vault
from app.vaults.scan import scan

DERIVED = {
    "notes": "SELECT f.path, n.title, n.properties::text, n.frontmatter_error, n.read_only "
    "FROM notes n JOIN files f USING (file_id)",
    "note_tags": "SELECT f.path, t.tag, t.tag_key FROM note_tags t JOIN files f USING (file_id)",
    "note_links": "SELECT f.path, l.ordinal, l.target, r.path, l.embed, l.heading, l.block, "
    "l.alias FROM note_links l JOIN files f USING (file_id) "
    "LEFT JOIN files r ON r.file_id = l.resolved_file_id",
}


def add_files(
    session: Session, vault_id: uuid.UUID, root: Path, known: dict[str, uuid.UUID] | None = None
) -> dict[str, uuid.UUID]:
    """Register scanned files not in `known` in `files`, as the identity layer (Task 10)
    will, and return their ids."""
    ids = {}
    for f in scan(root):
        if f.path in (known or {}):
            continue
        ids[f.path] = uuid.uuid7()
        session.add(
            File(
                file_id=ids[f.path],
                vault_id=vault_id,
                path=f.path,
                path_key=casefold_key(f.path),
                kind=f.kind,
                size=f.size,
                content_hash=f.content_hash,
            )
        )
    session.flush()
    return ids


def dump(session: Session) -> dict[str, list[tuple]]:
    return {
        table: sorted(session.execute(text(sql)).all(), key=repr) for table, sql in DERIVED.items()
    }


def make_vault(root: Path) -> None:
    (root / "Links.md").write_text(
        "---\ntags: [Topic, '#Other']\ntitle: Custom title\n---\n"
        "See [[Plan]], [[Projects/Plan#Goals|goals]], ![[pixel.png|300]], [[Missing]],\n"
        "[md](Welcome.md) and #inline #topic.\n"
    )
    (root / "Broken.md").write_text("---\ntags: [a\n---\nbody #b\n")
    (root / "Latin1.md").write_bytes(b"caf\xe9 [[Plan]]\n")


def test_drop_and_rebuild_gives_identical_index(obsidian_vault, session):
    make_vault(obsidian_vault)
    vault_id = open_vault(session, obsidian_vault)
    file_ids = add_files(session, vault_id, obsidian_vault)
    for path, file_id in file_ids.items():
        if path.endswith(".md"):
            index_file(session, vault_id, file_id, (obsidian_vault / path).read_bytes(), path)
    first = dump(session)
    notes = {row[0]: row for row in first["notes"]}
    assert notes["Links.md"][1:2] == ("Custom title",) and notes["Links.md"][3:] == (False, False)
    assert ("Latin1.md", "Latin1", None, False, True) in first["notes"]
    assert ("Broken.md", "Broken", None, True, False) in first["notes"]
    tags = {(p, k) for p, _, k in first["note_tags"] if p == "Links.md"}
    assert tags == {("Links.md", "topic"), ("Links.md", "other"), ("Links.md", "inline")}
    links = {(row[2], row[3]) for row in first["note_links"] if row[0] == "Links.md"}
    assert links == {
        ("Plan", "Projects/Plan.md"),
        ("Projects/Plan", "Projects/Plan.md"),
        ("pixel.png", "Attachments/pixel.png"),
        ("Missing", None),
        ("Welcome.md", "Welcome.md"),
    }
    files_before = session.execute(text("SELECT * FROM files ORDER BY path")).all()

    rebuild_index(session, vault_id, obsidian_vault)

    assert dump(session) == first
    assert session.execute(text("SELECT * FROM files ORDER BY path")).all() == files_before


def test_rebuild_reads_files_from_disk_and_skips_deleted(obsidian_vault, session):
    vault_id = open_vault(session, obsidian_vault)
    file_ids = add_files(session, vault_id, obsidian_vault)
    session.get(File, file_ids["Welcome.md"]).deleted = True
    rebuild_index(session, vault_id, obsidian_vault)
    titles = set(session.scalars(select(Note.title)))
    assert titles == {"Plan", "#hashtag note"}


def test_link_resolution_updates_when_target_appears(obsidian_vault, session):
    (obsidian_vault / "A.md").write_text("[[Missing]] and [[Plan]]\n")
    vault_id = open_vault(session, obsidian_vault)
    ids = add_files(session, vault_id, obsidian_vault)
    rebuild_index(session, vault_id, obsidian_vault)
    resolved = "SELECT target, resolved_file_id FROM note_links WHERE file_id = :f ORDER BY ordinal"
    assert session.execute(text(resolved), {"f": ids["A.md"]}).all() == [
        ("Missing", None),
        ("Plan", ids["Projects/Plan.md"]),
    ]

    (obsidian_vault / "Missing.md").write_text("here\n")
    (obsidian_vault / "Plan.md").write_text("closer\n")  # same folder as A.md now wins
    new = add_files(session, vault_id, obsidian_vault, ids)
    for path, file_id in new.items():
        index_file(session, vault_id, file_id, (obsidian_vault / path).read_bytes(), path)

    assert session.execute(text(resolved), {"f": ids["A.md"]}).all() == [
        ("Missing", new["Missing.md"]),
        ("Plan", new["Plan.md"]),
    ]


def test_indexing_one_vault_never_resolves_links_of_another(obsidian_vault, session, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "B.md").write_text("[[Lonely]]\n")
    other_id = open_vault(session, other)
    other_ids = add_files(session, other_id, other)
    rebuild_index(session, other_id, other)

    vault_id = open_vault(session, obsidian_vault)
    (obsidian_vault / "Lonely.md").write_text("only in the first vault\n")
    ids = add_files(session, vault_id, obsidian_vault)
    index_file(session, vault_id, ids["Lonely.md"], b"only in the first vault\n", "Lonely.md")

    resolved = "SELECT resolved_file_id FROM note_links WHERE file_id = :f"
    assert session.execute(text(resolved), {"f": other_ids["B.md"]}).scalar_one() is None


def test_downgrade_drops_the_index_tables(pg_url, engine):
    from sqlalchemy import inspect

    from tests.integration.test_migrations import alembic_downgrade

    assert {"files", "notes", "note_tags", "note_links"} <= set(inspect(engine).get_table_names())
    alembic_downgrade(pg_url, "0002")
    engine.dispose()
    assert set(inspect(engine).get_table_names()) == {"alembic_version", "vaults"}
