# Phase 1 Vault Storage Engine and Sync Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python vault engine that opens an existing Obsidian vault without writing to it, reads and edits notes byte-for-byte, detects external changes and renames, keeps an index and a history store that can be rebuilt, and a server-side sync prototype whose invariants I1–I6 hold over 10,000 seeded simulation runs (milestone M1).

**Architecture:** Library code only, in the existing backend modules: `app/vaults` (paths, file I/O, scanning, watcher), `app/notes` (parsing, frontmatter, extraction, identity), `app/sync` (history store, commit path, merge, push and pull). No HTTP endpoint is added except `GET /api/v1/meta/path-rules`; Phase 2 puts the API on these functions. The sync code is synchronous (SQLAlchemy `Session` on psycopg 3) because every commit does blocking `fsync` file I/O; Phase 2 calls it from a thread pool and the worker calls it directly.

**Tech Stack:** Python 3.14 (D10), SQLAlchemy 2, Alembic, PostgreSQL 18 with the Phase 0 extensions, `ruamel.yaml` (round-trip frontmatter), `markdown-it-py` (code and HTML ranges for extraction), `watchdog` (file events), `merge3` (line-based three-way merge), stdlib `compression.zstd` and `uuid.uuid7` (3.14), pytest and Hypothesis.

**Spec:** `docs/superpowers/specs/2026-10-17-opennote-architecture-design.md`, and the contracts it links, which are the real specification for this phase: `docs/architecture/storage-contract.md` (cited as "storage §n"), `docs/architecture/sync-protocol.md` ("sync §n"), `docs/development/testing-strategy.md` ("testing §n"), ADR-0002, ADR-0004, ADR-0005, ADR-0006, ADR-0017. Roadmap items P1-01 to P1-13 in `docs/ROADMAP.md`. Repository rules: `CLAUDE.md`.

## Decisions this plan needs

The architecture spec lists D1–D8. Phase 1 adds three; the plan is written with the recommended option and the PR stays open until Flemming answers.

| # | Question | Options | Recommended, and why |
|---|---|---|---|
| D9 | Which database does the sync prototype run on? | **PostgreSQL**: the real schema, migration and row lock; Phase 2 builds on it unchanged. **SQLite**: what sync §13 says today; faster seeds, but a second implementation of the commit path and a stand-in for PostgreSQL behaviour that testing §1 forbids | PostgreSQL. ADR-0004 says Phase 2's API is built on the prototype's commit path; on SQLite that path would be rewritten in Phase 2 and the simulation would not have tested it. Each seed uses a fresh `vault_id`, so seeds need no truncation. Sync §13 is updated in this PR to say PostgreSQL |
| D10 | Raise the backend's Python floor from 3.13 to 3.14? | **3.14**: stdlib `compression.zstd` and `uuid.uuid7()`, CI drops the 3.13 leg, tests run on the interpreter the images ship (R20). **Keep 3.13**: add the `zstandard` package and a hand-written UUIDv7 helper | 3.14. Two fewer pieces of code to own, and the only runtime is already 3.14. Cost: the cloud container has Python 3.13 only, so an implementer there installs a 3.14 build first (Task 1) |
| D11 | Time box for the sync prototype (Tasks 12–15)? | **1 week** of working time, as ADR-0004 estimates. **2 weeks** | 1 week. When it runs out: stop, record which invariants hold and which seeds fail in `docs/IMPLEMENTATION_STATUS.md`, and put the choice (extend, or change the protocol) to Flemming. Tasks 1–11 are not time-boxed |

## Global Constraints

- Bytes are sacred: `write(read(bytes)) == bytes` for every note; edits are text replacements on the original string, never parse-and-re-render (storage §2.1).
- Opening, viewing, scanning or indexing a vault writes nothing to it, `.opennote/config.json` included; `id` is never inserted except into notes OpenNote creates (storage §1, §2.4, D5).
- OpenNote never auto-writes `created` or `modified`; never writes inside `.obsidian/` (storage §1.1, §2.2).
- Everything derived (index, history, sync state) lives outside the vault (storage §1.3).
- Paths: vault-relative, `/`-separated, NFC; containment through `dir_fd` and `O_NOFOLLOW`; symlinks are never followed (storage §1.1, §3).
- Writes: temp file `.<name>.<random>.opennote-tmp` in the target directory, `fsync`, `rename`, `fsync` the directory; abort when the on-disk hash is not the expected base hash (storage §4).
- `content_hash = "sha256:" + lowercase hex` of the exact bytes (storage §6). Files are hashed in 1 MiB chunks, never read whole (`CLAUDE.md` §24).
- Commit order: history object, PostgreSQL transaction, JSONL log line, vault file; client acknowledged only after the vault file (sync §2.3). No decision uses wall-clock time (I6).
- Merges run only on the server; no conflict markers are ever written into a note (sync §6).
- Python only through the repository-root `.venv`; every new package pinned with `==` in `backend/requirements.txt` or `requirements-dev.txt`, then `make constraints` (`CLAUDE.md` §3, R104).
- Schema changes only through Alembic migrations that upgrade and downgrade in CI (`CLAUDE.md` §17).
- Tests use real temporary directories and real PostgreSQL; nothing under test is mocked; randomized tests are seeded and print the seed (testing §1).
- Work on `feature/phase-1-storage-sync` in `.worktrees/storage/`; one commit per task; squash merge after CI is green; `ponytail-audit` before the PR is marked ready (`CLAUDE.md` §6, §28).
- Every prompt is recorded in `.conversations/YYYY-MM-DD-phase-1-storage-sync.md`, rulings continuing from R124.

## Review Focus

- A vault copied from a Mac holds NFD file names on the Linux server: the file is indexed under its NFC path, opened by its on-disk name, and no second entry appears after a rescan. Test in Task 2 (`test_nfd_name_on_disk_resolves`) and Task 6 (`test_scan_reports_nfc_paths_for_nfd_names`).
- A symlink inside the vault pointing outside it, or a directory swapped for a symlink between check and use: never followed, reported as unsupported, write refused. Test in Task 2 (`test_symlinked_parent_is_refused`) and Task 8 (`test_atomic_write_refuses_symlinked_directory`).
- Disk full or read-only vault during a write (`ENOSPC`, `EROFS`): the target keeps its old bytes, the temp file is removed, the error reaches the caller. Test in Task 8 (`test_enospc_leaves_old_bytes_and_no_temp`).
- A 2 GiB attachment or a 10 MB note: hashed in chunks with bounded memory; a note above the 16 MiB limit of the API contract is indexed as an opaque read-only file, not parsed. Test in Task 6 (`test_hashing_streams_large_file`, `test_oversized_note_is_opaque`).
- Obsidian saves the same note while a commit is between its PostgreSQL step and its vault-file step: the file is not overwritten; the on-disk edit becomes an `update` against the previous revision and is merged (sync §2.3 last paragraph). Test in Task 12 (`test_external_edit_during_commit_is_merged_not_clobbered`).

---

### Task 1: Python 3.14 floor and Phase 1 dependencies (D10)

**Files:**
- Modify: `backend/pyproject.toml` (`requires-python = ">=3.14"`, ruff `target-version`, mypy `python_version`), `.github/workflows/backend.yml` (matrix `["3.14"]`), `backend/requirements.txt`, `backend/requirements-dev.txt`, `backend/constraints.txt` (regenerated), `docs/development/versions.md` (rows for the new packages, the Python decision), `docs/development/setup.md`

- [ ] **Step 1:** In the cloud container, install a Python 3.14 build (python-build-standalone release from GitHub, checksum verified) and recreate `.venv` with it; record the source in `versions.md`.
- [ ] **Step 2:** Add pins for the latest stable releases, resolved on the day: runtime `ruamel.yaml`, `markdown-it-py`, `watchdog`, `merge3`; dev `hypothesis`. (On 2026-11-01: 0.19.1, —, 7.0.0, 1.0.0, 6.170.14.) Run `make constraints PYTHON=python3.14`.
- [ ] **Step 3:** Run `make lint typecheck test`; expected: all pass on 3.14, the constraints check passes.
- [ ] **Step 4:** Commit `chore(backend): python 3.14 floor and phase 1 dependencies`.

### Task 2: Path rules and containment (P1-04)

**Files:**
- Create: `backend/app/vaults/paths.py`, `backend/app/vaults/fsio.py`, `backend/app/api/vaults_meta.py`
- Modify: `backend/app/api/main.py` (`ROUTERS`, `KEYLESS_ROUTES` gains `("GET", "/api/v1/meta/path-rules")`, already listed in API contract §2), `backend/tests/unit/test_route_auth.py` (the exact-set test), `docs/api/openapi.json` (`make openapi`)
- Test: `backend/tests/unit/vaults/test_paths.py`, `backend/tests/unit/vaults/test_fsio_containment.py`, `backend/tests/unit/test_path_rules_endpoint.py`

**Interfaces:**
- Produces: `FileKind = Literal["note", "attachment", "config", "obsidian_config", "ignored", "temp"]`; `classify(path: str) -> FileKind` (storage §1.1 table, first match wins, `.md` case-insensitive, `.canvas`/`.base` are `attachment`).
- Produces: `normalize(path: str) -> str` (NFC, no other change); `casefold_key(path: str) -> str` (NFC then `str.casefold()`).
- Produces: `PathViolation(code: str, segment: str | None)`; `validate(path: str, *, note: bool) -> list[PathViolation]` with codes `empty_segment`, `dot_segment`, `absolute`, `backslash`, `control_char`, `forbidden_char`, `link_char` (note names only), `trailing_space_or_dot`, `segment_too_long` (>255 UTF-8 bytes), `path_too_long` (>1024), `reserved_name`, `leading_dot`. Case-fold collisions need the folder listing, so they are checked by the caller with `casefold_key`.
- Produces: `PATH_RULES: dict[str, object]`, the JSON served at `GET /api/v1/meta/path-rules` (limits, forbidden characters, reserved names, NFC, case-insensitive collision rule); the endpoint is keyless.
- Produces in `fsio.py`: `open_root(root: Path) -> int` (directory fd); `open_parent(root_fd: int, rel: str, *, create: bool = False) -> tuple[int, str]` walks each segment with `os.open(seg, O_DIRECTORY | O_NOFOLLOW, dir_fd=...)`, returns the parent fd and the leaf name; raises `PathEscapeError` on a symlink or a missing segment; when the NFC name is absent it falls back to the one directory entry whose NFC form matches.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("path", ["../x.md", "a/../../x.md", "/etc/passwd", "a\\b.md", "a//b.md", "a/./b.md", "con.md", "a/b .md", "x\x00.md", ".hidden.md"])
def test_traversal_and_bad_names_rejected(path): assert validate(path, note=True)

def test_link_chars_only_rejected_in_notes():
    assert {v.code for v in validate("a#b.md", note=True)} == {"link_char"}
    assert validate("a#b.png", note=False) == []

@given(st.text())  # seeded via the Hypothesis profile
def test_validated_paths_never_escape(tmp_path_factory, path):
    if not validate(path, note=False):
        fd, leaf = open_parent(open_root(root := tmp_path_factory.mktemp("v")), path, create=True)
        assert Path(os.readlink(f"/proc/self/fd/{fd}")).is_relative_to(root)

def test_symlinked_parent_is_refused(tmp_path): ...   # vault/a -> /tmp/outside; open_parent(root, "a/x.md") raises PathEscapeError
def test_nfd_name_on_disk_resolves(tmp_path): ...     # file created as "Café.md"; open_parent(root, "Café.md") returns that entry
def test_path_rules_endpoint_is_keyless(client): assert client.get("/api/v1/meta/path-rules").status_code == 200
```

- [ ] **Step 2:** Run `.venv/bin/pytest backend/tests/unit/vaults backend/tests/unit/test_path_rules_endpoint.py -v`; expected: FAIL (modules missing).
- [ ] **Step 3:** Implement the interfaces above.
- [ ] **Step 4:** Run the tests, `make openapi`, and the existing `test_route_auth.py`; expected: PASS, drift check clean after committing `openapi.json`.
- [ ] **Step 5:** Commit `feat(vaults): path rules, containment and path-rules endpoint`.

### Task 3: Byte-preserving note reader and the compatibility corpus (P1-02, P1-10 part 1)

**Files:**
- Create: `backend/app/notes/document.py`
- Create: `tests/compatibility/vaults/<case>/` (one note per case plus `expected.json`), `tests/compatibility/README.md` (case format)
- Test: `backend/tests/unit/notes/test_document.py`, `backend/tests/compatibility/test_corpus_roundtrip.py`, `backend/tests/unit/notes/test_document_properties.py` (Hypothesis)

**Interfaces:**
- Produces: `@dataclass(frozen=True) class NoteDocument: raw: bytes; text: str | None` (`None` when not valid UTF-8: read-only opaque note); `bom: bool`; `newline: Literal["\n", "\r\n"]` (dominant ending, LF for new files); `frontmatter: slice | None` (character span of the YAML between the delimiters, in `text`); `body: slice`.
- Produces: `parse_note(raw: bytes) -> NoteDocument`; frontmatter only when the first line after an optional BOM is exactly `---` and a later line is exactly `---` or `...` (storage §2.2).
- Produces: `replace_span(doc: NoteDocument, span: slice, new: str) -> bytes`, the only way any code edits a note: re-encodes `text` with the replacement, keeps the BOM, and converts `\n` in `new` to `doc.newline`; raises `ReadOnlyNote` when `doc.text is None`.
- Corpus format, consumed by Tasks 4, 5, 6: `expected.json` = `{"frontmatter": {...} | null, "frontmatter_error": bool, "links": [...], "embeds": [...], "tags": [...], "external_urls": [...]}`; Task 3 adds the cases of testing §3 "Frontmatter" and "Syntax preservation" and fills only the frontmatter keys; Tasks 5 and 6 add the other groups.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("case", corpus_cases())
def test_corpus_roundtrip_is_byte_identical(case):
    raw = case.note_bytes(); assert parse_note(raw).raw == raw

def test_crlf_note_edit_keeps_crlf():
    doc = parse_note(b"---\r\ntitle: a\r\n---\r\nline\r\n")
    assert replace_span(doc, doc.body, "x\ny\n") == b"---\r\ntitle: a\r\n---\r\nx\r\ny\r\n"

def test_bom_kept_and_frontmatter_found_after_bom(): ...
def test_windows_1252_note_is_read_only(): assert parse_note("café".encode("cp1252")).text is None
def test_no_trailing_newline_preserved(): ...

@given(markdown_documents())   # grammar of corpus constructs, CRLF/LF/mixed, optional BOM
def test_edit_changes_only_the_span(raw): ...  # bytes before and after the replaced span are unchanged
```

- [ ] **Step 2:** Run them; expected: FAIL.
- [ ] **Step 3:** Implement `document.py` and write the corpus cases; the 10 MB note is generated by a fixture, not committed.
- [ ] **Step 4:** Run; expected: PASS. Add a `compatibility` marker so CI reports the corpus separately.
- [ ] **Step 5:** Commit `feat(notes): byte-preserving note reader and compatibility corpus`.

### Task 4: Round-trip frontmatter editor (P1-03)

**Files:**
- Create: `backend/app/notes/frontmatter.py`
- Test: `backend/tests/unit/notes/test_frontmatter.py`, corpus cases for comments, anchors, flow style, duplicate keys

**Interfaces:**
- Consumes: `NoteDocument`, `replace_span` (Task 3).
- Produces: `Properties = dict[str, object]`; `read_properties(doc: NoteDocument) -> tuple[Properties | None, bool]` (properties, `frontmatter_error`); `tags` and `aliases` normalized to lists on read (comma-separated legacy string accepted).
- Produces: `DELETE = object()`; `edit_properties(doc: NoteDocument, changes: Mapping[str, object]) -> bytes` for top-level keys `tags`, `aliases`, `id`, and `opennote` (a mapping merged key by key); raises `FrontmatterInvalid` on invalid YAML (duplicate keys count as invalid) and `PropertyNotEditable` for any other key. A note without frontmatter gains a block at the top only when a change is non-empty.

Algorithm (the tests do not determine it): load the frontmatter with `ruamel.yaml` round-trip mode to find each top-level key's line range (`.lc`); for each changed key, render only that key with a round-trip dumper configured from the existing block's indentation, and splice it over that key's line range with `replace_span`; a new key is appended after the last key. Untouched keys are never re-dumped, so their quoting, comments and order cannot change.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("case", corpus_cases(with_valid_frontmatter=True))
def test_tag_edit_changes_only_the_tags_node(case):
    doc = parse_note(case.note_bytes()); out = edit_properties(doc, {"tags": ["x"]})
    assert_only_key_lines_changed(case.note_bytes(), out, "tags")

def test_comments_and_quoting_of_other_keys_survive(): ...
def test_invalid_yaml_refuses_edit_but_reads_body():
    doc = parse_note(b"---\na: [\n---\nbody\n")
    assert read_properties(doc) == (None, True)
    with pytest.raises(FrontmatterInvalid): edit_properties(doc, {"tags": ["x"]})
def test_duplicate_keys_are_invalid(): ...
def test_created_and_modified_never_touched(): ...
def test_editing_other_top_level_key_refused(): ...
```

- [ ] **Step 2:** Run; expected: FAIL. **Step 3:** Implement. **Step 4:** Run; expected: PASS.
- [ ] **Step 5:** Commit `feat(notes): round-trip frontmatter editor`.

### Task 5: Link, embed and tag extraction and Obsidian link resolution (P1-06, P1-10 part 2)

**Files:**
- Create: `backend/app/notes/extract.py`, `backend/app/notes/links.py`
- Create: corpus cases for testing §3 "Links" and "Tags"
- Test: `backend/tests/unit/notes/test_extract.py`, `backend/tests/unit/notes/test_links.py`, `backend/tests/compatibility/test_corpus_extraction.py`

**Interfaces:**
- Consumes: `NoteDocument` (Task 3), `normalize`, `casefold_key` (Task 2).
- Produces: `Link(target: str, heading: str | None, block: str | None, alias: str | None, embed: bool, markdown: bool)`; `Extraction(links: list[Link], tags: list[str], external_urls: list[str])`; `extract(doc: NoteDocument) -> Extraction`. Tags are kept as written (without the `#`); callers compare them case-insensitively.
- Produces: `resolve(link: Link, from_path: str, paths: Sequence[str]) -> str | None` per storage §2.5 (vault-root then relative for targets with `/`; otherwise by name, preferring the linking folder, then the shortest path, then lexical order; NFC and case-insensitive).

Approach: `markdown-it-py` (CommonMark, `html` on) gives the line and character ranges of fences, indented code, inline code, HTML blocks and inline HTML; `%%…%%` ranges are found by scanning. Wiki-links, Markdown links and tags are matched with regular expressions over the remaining text only. Headings' leading `#` and numeric-only tags (`#123`) are not tags.

- [ ] **Step 1:** Write tests: every case's extraction equals its `expected.json`; `test_links_in_code_not_extracted`; `test_url_fragment_is_not_a_tag`; `test_ambiguous_name_prefers_same_folder_then_shortest`; `test_unresolved_link_returns_none`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Run; PASS.
- [ ] **Step 5:** Commit `feat(notes): link, embed and tag extraction`.

### Task 6: Vault registry, scanner and attachment classification (P1-01, P1-09)

**Files:**
- Create: `backend/app/vaults/config.py`, `backend/app/vaults/scan.py`, `backend/app/vaults/models.py`, `backend/migrations/versions/0002_vaults.py`
- Modify: `backend/app/core/db.py` (`make_sync_engine(settings: Settings) -> Engine`, same URL, same 5 s connect timeout)
- Create: corpus cases for testing §3 "Paths" and "Obsidian-specific files" (as vault trees)
- Test: `backend/tests/unit/vaults/test_scan.py`, `backend/tests/unit/vaults/test_config.py`, `backend/tests/integration/test_vault_registry.py`

**Interfaces:**
- Produces: table `vaults(id uuid pk, name text, root_path text unique)`; `VaultConfig` (`schema_version`, `vault_id`, `name`, unknown keys kept verbatim) with `read_config(root_fd: int) -> VaultConfig | None` and `write_config(root_fd: int, cfg: VaultConfig) -> None` (atomic, only from an explicit register call).
- Produces: `register_vault(session: Session, root: Path, name: str) -> uuid.UUID` (writes `.opennote/config.json`, the only vault write in this task) and `open_vault(session: Session, root: Path) -> uuid.UUID` (reuses the config's `vault_id` when present, otherwise an id kept in `vaults` only; writes nothing).
- Produces: `ScannedFile(path: str, disk_name: str, kind: FileKind, size: int, mtime_ns: int, inode: int, content_hash: str, path_warning: bool)`; `scan(root: Path) -> Iterator[ScannedFile]` (no symlinks followed; unsupported entries logged and skipped; NFC `path`, raw `disk_name`); `hash_file(dir_fd: int, name: str) -> str` (1 MiB chunks). `MAX_NOTE_BYTES = 16 * 1024 * 1024`: a larger `.md` is scanned with `kind="attachment"` and flagged read-only.

- [ ] **Step 1: Write the failing tests**

```python
def test_open_existing_vault_writes_nothing(obsidian_vault, session):
    before = tree_digest(obsidian_vault)   # paths, bytes, mode, mtime_ns of every entry incl. directories
    open_vault(session, obsidian_vault); list(scan(obsidian_vault))
    assert tree_digest(obsidian_vault) == before

def test_obsidian_dir_and_trash_are_ignored(): ...
def test_scan_reports_nfc_paths_for_nfd_names(): ...
def test_hashing_streams_large_file(tmp_path): ...  # 2 GiB sparse file; tracemalloc peak < 8 MiB
def test_oversized_note_is_opaque(): ...
def test_config_unknown_keys_preserved(): ...
def test_higher_schema_version_opens_read_only(): ...
```

- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement; migration `0002` creates `vaults`. **Step 4:** Run, plus `alembic upgrade head` / `downgrade -1` in the integration suite; PASS.
- [ ] **Step 5:** Commit `feat(vaults): vault registry and scanner`.

### Task 7: Index schema rebuildable from the vault (P1-11)

**Files:**
- Create: `backend/app/notes/models.py`, `backend/app/notes/index.py`, `backend/migrations/versions/0003_index.py`
- Test: `backend/tests/integration/test_index_rebuild.py`

**Interfaces:**
- Consumes: `scan`, `parse_note`, `read_properties`, `extract`, `resolve`.
- Produces tables: `files(file_id uuid pk, vault_id fk, path text, path_key text, kind text, size bigint, content_hash text, revision int, deleted bool, unique(vault_id, path_key) where not deleted)` — the identity registry, **not** derived, never dropped by a rebuild; and the derived tables `notes(file_id pk, title, properties jsonb, frontmatter_error bool, read_only bool)`, `note_tags(file_id, tag, tag_key)`, `note_links(file_id, target, resolved_file_id null, embed, heading, block, alias, ordinal)`.
- Produces: `index_file(session: Session, vault_id: UUID, file_id: UUID, raw: bytes, path: str) -> None` (replaces the derived rows for one file); `rebuild_index(session: Session, vault_id: UUID, root: Path) -> None` (deletes and recreates the derived rows for every live `files` row, in batches of 500, then resolves links).

- [ ] **Step 1:** Write `test_drop_and_rebuild_gives_identical_index` (index the corpus vault, dump the derived tables sorted, rebuild, dump again, compare) and `test_link_resolution_updates_when_target_appears`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Run; PASS (migration up/down included).
- [ ] **Step 5:** Commit `feat(notes): rebuildable note index`.

### Task 8: Atomic writes with the external-change guard (P1-07)

**Files:**
- Modify: `backend/app/vaults/fsio.py`
- Test: `backend/tests/unit/vaults/test_atomic_write.py`

**Interfaces:**
- Consumes: `open_parent`, `hash_file`.
- Produces: `atomic_write(root_fd: int, rel: str, data: bytes, *, expected_hash: str | None) -> str` (returns the new hash; `expected_hash=None` means the path must not exist); `ExternalChangeError(path, found_hash)`; `move_to(root_fd: int, rel: str, dest_dir: Path) -> Path` for recovery-area deletes (storage §4.5); `clean_stale_temps(root: Path, older_than_ns: int) -> int`.
- Steps inside `atomic_write`, in order, each a named point for the crash test: `temp_written`, `temp_synced`, `guard_checked`, `renamed`, `dir_synced`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("point", ["temp_written", "temp_synced", "guard_checked", "renamed", "dir_synced"])
def test_crash_at_each_point_leaves_old_or_new_bytes(tmp_path, point):
    # a subprocess runs atomic_write with os.fsync/os.rename wrapped to os._exit(1) at `point`
    assert target_bytes(tmp_path) in (OLD, NEW)

def test_external_edit_is_not_clobbered(tmp_path): ...       # file changed after base hash taken → ExternalChangeError, file keeps external bytes
def test_enospc_leaves_old_bytes_and_no_temp(tmp_path): ... # small tmpfs mount if permitted, else os.write patched to raise ENOSPC
def test_atomic_write_refuses_symlinked_directory(tmp_path): ...
def test_temp_name_is_hidden_and_ignored_by_classify(): ...
```

The crash point is injected by wrapping `os.fsync`/`os.rename` in the subprocess helper; production code carries no test hook. A real power loss is not testable here and is stated as such in `IMPLEMENTATION_STATUS.md`.

- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Run; PASS.
- [ ] **Step 5:** Commit `feat(vaults): atomic writes with external-change guard`.

### Task 9: History store (P1-13)

**Files:**
- Create: `backend/app/sync/history.py`
- Test: `backend/tests/unit/sync/test_history.py`

**Interfaces:**
- Produces: `class HistoryStore` with `__init__(self, history_root: Path, vault_id: UUID)`; `put(self, data: bytes) -> str` (content hash; writes `objects/<aa>/<rest>` zstd-compressed via a temp file + rename + fsync; a second put of the same bytes is a no-op); `get(self, content_hash: str) -> bytes` (verifies the hash after decompressing, raises `HistoryCorrupt`); `append_log(self, entry: RevisionLogEntry) -> None` (one JSON line to `log/<YYYY-MM>.jsonl`, `fsync`); `read_log(self) -> Iterator[RevisionLogEntry]` (in file order, tolerating one torn last line).
- Produces: `@dataclass(frozen=True) class RevisionLogEntry: seq: int; file_id: UUID; revision: int; path: str; kind: str; content_hash: str | None; deleted: bool; device_id: str; op: str; committed_at: str` (`committed_at` is informational only, I6). The month of the log file comes from `committed_at`.

- [ ] **Step 1:** Tests: `test_put_get_roundtrip_and_dedup`, `test_get_detects_corruption`, `test_log_survives_torn_last_line`, `test_objects_are_compressed` (a 1 MB repetitive note stores < 100 KB).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement with `compression.zstd`. **Step 4:** Run; PASS.
- [ ] **Step 5:** Commit `feat(sync): content-addressed history store`.

### Task 10: Identity registry and rename detection (P1-05)

**Files:**
- Create: `backend/app/notes/identity.py`
- Test: `backend/tests/integration/test_identity.py`

**Interfaces:**
- Consumes: `files` table (Task 7), `ScannedFile` (Task 6), `read_properties` (Task 4).
- Produces: `FsChange(kind: Literal["create", "update", "delete", "move"], file_id: UUID | None, path: str, new_path: str | None, content_hash: str | None)`; `diff_scan(session: Session, vault_id: UUID, scanned: Iterable[ScannedFile]) -> list[FsChange]` compares a scan with the live `files` rows and pairs every delete with a create in the same batch that has the same content hash, or the same frontmatter `id`, into one `move` (several candidates: same folder first, then lexical order). A frontmatter `id` already owned by another live file is ignored for the newer file, which gets a fresh `uuid7()` (storage §2.4). Nothing is written to any file.

- [ ] **Step 1:** Tests: `test_external_rename_keeps_identity`, `test_rename_with_edit_in_same_batch_is_delete_plus_create` (documented limit), `test_frontmatter_id_wins_over_hash`, `test_copied_file_with_duplicate_id_gets_new_identity`, `test_no_id_written_on_open` (tree digest unchanged).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Run; PASS.
- [ ] **Step 5:** Commit `feat(notes): identity registry and rename detection`.

### Task 11: Watcher, reconciliation scan and loop suppression (P1-08)

**Files:**
- Create: `backend/app/vaults/watch.py`
- Test: `backend/tests/integration/test_watch.py`

**Interfaces:**
- Consumes: `scan`, `diff_scan`, `clean_stale_temps`.
- Produces: `class VaultWatcher` with `__init__(self, root: Path, vault_id: UUID, session_factory: sessionmaker[Session], on_changes: Callable[[list[FsChange]], None], *, debounce_s: float = 0.5, rescan_s: float = 900)`, `start()`, `stop()`, `note_own_write(self, path: str, content_hash: str) -> None`. A watchdog `Observer` collects paths; after 500 ms without events for a path the watcher re-scans those paths and hands the resulting `FsChange`s to `on_changes`. An event whose new hash equals the hash recorded by `note_own_write` for that path is dropped (I5). A full reconciliation runs at `start()`, every `rescan_s`, and whenever the observer reports an error or overflow (watchdog's emitter dies or raises), using a `(size, mtime_ns, inode)` cache so only changed files are hashed; it also removes `.opennote-tmp` files older than one hour.
- Process placement (which process runs the watcher, one per vault across replicas) is Phase 2 work and not part of this task.

- [ ] **Step 1:** Tests: `test_external_create_edit_move_delete_detected_within_2s` (four sub-cases, each asserting the `FsChange` within 2 s), `test_own_write_is_suppressed`, `test_overflow_triggers_reconcile` (calls the overflow handler directly and asserts a full rescan found a change made while events were dropped), `test_stale_temp_removed`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Run 20 times (`pytest --count` is not installed: a shell loop) to check the 2 s timing is not flaky; PASS.
- [ ] **Step 5:** Commit `feat(vaults): watcher with reconciliation and loop suppression`.

### Task 12: Sync schema and commit path (P1-12 part 1) — time box starts (D11)

**Files:**
- Create: `backend/app/sync/models.py`, `backend/app/sync/commit.py`, `backend/migrations/versions/0004_sync.py`
- Test: `backend/tests/integration/sync/test_commit.py`

**Interfaces:**
- Consumes: `HistoryStore`, `atomic_write`, `ExternalChangeError`, `files`, `index_file`.
- Produces tables: `vault_seq(vault_id pk, last_seq bigint)`; `revisions(vault_id, seq bigint, file_id, revision int, path, kind, content_hash null, deleted, device_id, op, committed_at, pk(vault_id, seq), unique(file_id, revision))`; `client_ops(vault_id, client_op_id uuid, result jsonb, seq bigint, pk(vault_id, client_op_id))`; `conflicts(id uuid pk, vault_id, file_id, copy_file_id, base_revision, their_revision, status text)`.
- Produces: operation types `Create`, `Update`, `Move`, `Delete`, `Restore` (frozen dataclasses with the fields of sync §3); `OpResult(status: Literal["applied", "merged", "conflict", "rejected", "duplicate"], file_id: UUID, revision: int | None, seq: int | None, content_hash: str | None, path: str | None, problem: dict | None)`.
- Produces: `class Committer` with `__init__(self, session_factory: sessionmaker[Session], history: HistoryStore, vault_root_fd: int, vault_id: UUID)`, `commit(self, op: Operation, device_id: str, blob: bytes | None) -> OpResult` running the five steps of sync §2.3 in order, and `recover(self) -> None` applying the crash table of sync §2.3. `commit` takes `SELECT … FOR UPDATE` on `vault_seq` first, which serializes commits per vault. Merge (Task 13) is called from `commit` when `base_revision < current`.
- Crash points for the simulation: `Committer` accepts an optional `crash: Callable[[str], None]` called after each step with `"history"`, `"db"`, `"log"`, `"vault"`; production passes nothing.

- [ ] **Step 1: Write the failing tests**

```python
def test_seq_is_gap_free_under_concurrent_commits(committer_factory): ...  # 4 threads x 50 commits on one vault → seqs 1..200
@pytest.mark.parametrize("point", ["history", "db", "log", "vault"])
def test_crash_then_recover_restores_consistency(point): ...  # log, DB and vault agree after recover(); retry returns duplicate
def test_retry_with_same_client_op_id_returns_duplicate(): ...
def test_external_edit_during_commit_is_merged_not_clobbered(): ...  # file edited between "log" and "vault" → on-disk edit committed as update vs previous revision
def test_log_rebuild_reproduces_revisions(): ...  # drop revisions rows, rebuild from read_log(), compare
```

- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Run; PASS (migration up/down included).
- [ ] **Step 5:** Commit `feat(sync): revisions, change sequence and commit path`.

### Task 13: Server-side merge (P1-12 part 2)

**Files:**
- Create: `backend/app/sync/merge.py`
- Test: `backend/tests/unit/sync/test_merge.py`

**Interfaces:**
- Consumes: `parse_note`, `read_properties`, `edit_properties`.
- Produces: `MergeResult(clean: bool, data: bytes | None)`; `merge_note(base: bytes, theirs: bytes, ours: bytes) -> MergeResult` per sync §6 steps 2–6: `ours == theirs` is clean with `theirs`; frontmatter merged key by key on parsed YAML and re-emitted by `edit_properties` on `theirs`, a key changed on both sides to different values is unclean; invalid YAML on any side → whole file merged as text; body merged with `merge3.Merge3` over lines split with `keepends=True`, any conflict region is unclean. Line endings follow `theirs`.
- Produces: `conflict_copy_path(path: str, device_name: str, day: str, taken: Callable[[str], bool]) -> str` (`<name> (conflict <device> <yyyy-mm-dd>)<ext>`, then ` 2`, ` 3`); `day` is passed in, so no decision reads the clock (I6).

- [ ] **Step 1:** Tests: `test_non_overlapping_edits_merge`, `test_overlapping_edits_conflict_without_markers` (`b"<<<<<<<" not in` any output), `test_frontmatter_key_merge`, `test_both_sides_change_same_key_conflict`, `test_crlf_preserved_in_merge`, and a Hypothesis property: for random `base`, edits on disjoint line ranges always merge cleanly and contain both edits.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Run; PASS.
- [ ] **Step 5:** Commit `feat(sync): server-side three-way merge`.

### Task 14: Push, pull, snapshot and server-side changes (P1-12 part 3)

**Files:**
- Create: `backend/app/sync/service.py`, `backend/app/sync/cursor.py`
- Test: `backend/tests/integration/sync/test_service.py`

**Interfaces:**
- Consumes: `Committer`, `merge_note`, `conflict_copy_path`, `FsChange`.
- Produces: `encode_cursor(vault_id: UUID, seq: int) -> str` and `decode_cursor(cursor: str, vault_id: UUID) -> int` (base64url of version, vault, seq; rejects another vault's cursor); `CursorExpired` when `seq` is older than the retention window.
- Produces: `push(committer: Committer, device_id: str, ops: Sequence[Operation], blobs: Mapping[str, bytes]) -> list[OpResult]` (max 100 ops, in order, each independent); `changes(session: Session, vault_id: UUID, cursor: str | None, limit: int = 500) -> ChangesPage(entries: list[ChangeEntry], next_cursor: str, has_more: bool)`; `snapshot(session: Session, vault_id: UUID) -> list[ChangeEntry]`; `ingest_fs_changes(committer: Committer, changes: list[FsChange]) -> list[OpResult]` (device `server-fs`, base = last known revision, sync §7).
- Concurrent-pair rules of sync §6 (move vs update, move vs move, update vs delete "edit wins", create vs create, attachment vs attachment) are implemented here or in `Committer`, each with a test named after its row.
- Retention: `RETENTION_SEQ_WINDOW` is expressed in sequence numbers for the prototype (the simulation cannot wait 90 days and I6 forbids clocks in decisions); the production rule in days is Phase 5 (P5-07). Recorded as a ruling.

- [ ] **Step 1:** Tests, one per row of the sync §4 pull table, the sync §5 result table and the sync §6 "Other cases" table, plus `test_cursor_from_other_vault_rejected` and `test_expired_cursor_raises`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Run; PASS.
- [ ] **Step 5:** Commit `feat(sync): push, pull, snapshot and server-side changes`.

### Task 15: Sync simulation harness (P1-12 part 4) — time box ends (D11)

**Files:**
- Create: `backend/tests/sync_sim/__init__.py`, `client.py` (simulated client: `files`, `bases`, `outbox`, `cursor`, local vault directory, the loop of sync §9), `world.py` (server `Committer`, clients, external editors, network with drop/duplicate/reorder/partition), `invariants.py` (I1–I6 plus testing §4's extra checks), `test_simulation.py` (seeded runs), `test_state_machine.py` (Hypothesis `RuleBasedStateMachine` for shrinking), `regressions/` (one test per failing seed found)
- Modify: `.github/workflows/backend.yml` (500 seeds in the `test` job; a nightly `schedule` job running 10,000 seeds), `backend/pyproject.toml` (`sync_sim` marker), `Makefile` (`make sync-sim SEEDS=…`)

**Interfaces:**
- Consumes: everything in Tasks 9–14.
- Produces: `run_seed(seed: int, *, clients: int, steps: int, engine: Engine, tmp: Path) -> SimReport` (each seed uses a fresh `vault_id` and fresh directories, so seeds share one database without truncation); `check_invariants(world: World) -> list[Violation]`; a failure prints `seed=<n>` and the shrunk action list.
- Actions per step, chosen by the seeded RNG: client edit/create/move/delete of notes and attachments, external editor on a client vault or the server vault, go offline/online, push, pull, crash at each `Committer` crash point and between client steps, duplicate or reorder a request, expire a cursor.
- I6 is checked by running each seed twice with the process clock shifted (`committed_at` and conflict-copy day supplied from a skewed fake) and comparing final states.

- [ ] **Step 1:** Write `check_invariants` against hand-built worlds that violate each invariant once (`test_invariant_checker_catches_lost_edit`, …) so the checker itself is tested.
- [ ] **Step 2:** Run 500 seeds; expected at first: failures; each failing seed becomes a file in `regressions/` before its fix (`CLAUDE.md` §9).
- [ ] **Step 3:** Fix the code (or, if the protocol itself is wrong, stop and write the change to `sync-protocol.md` for Flemming's review: protocol changes are not made silently).
- [ ] **Step 4:** Run 10,000 seeds locally (`make sync-sim SEEDS=10000`) and record the wall time; expected: zero violations. Measure the 500-seed time; if the per-push run exceeds 5 minutes, record it and propose the fix (fewer steps per seed, or `pytest-xdist`) rather than adding a dependency unasked.
- [ ] **Step 5:** Commit `test(sync): seeded multi-client simulation harness`.

### Task 16: Milestone M1 close-out

**Files:**
- Modify: `docs/ROADMAP.md` (P1 rows), `docs/IMPLEMENTATION_STATUS.md`, `docs/architecture/sync-protocol.md` (§13 and anything Task 15 changed, with Flemming's approval), `docs/development/testing-strategy.md` (compatibility and simulation rows now live), `docs/development/setup.md`, this plan's Errata, `.conversations/2026-…-phase-1-storage-sync.md`

- [ ] **Step 1:** Fresh clone: `make bootstrap`, `make lint typecheck test`, `make sync-sim SEEDS=10000`; all five workflows green on the PR, and one nightly 10,000-seed run green.
- [ ] **Step 2:** Run `ponytail-audit`; apply only findings in this branch's code.
- [ ] **Step 3:** Set each P1 row to `COMPLETED` only where its acceptance criterion was observed passing, with the run link; anything else stays `TESTING` with the gap named.
- [ ] **Step 4:** Commit `docs: phase 1 status`, open the PR, request `@coderabbitai review`, squash merge after Flemming's go.

---

## Out of scope for Phase 1

HTTP endpoints other than path-rules (Phase 2, P2-04 builds them on `push`/`changes`); authentication; the WebSocket event channel; resumable blob upload (P5-02); which process runs the watcher and how replicas share a vault (Phase 2); Swift parsing parity (P4-01, which reuses this corpus); history GC and retention in days (P5-07); competing-sync-tool detection (P5-08).

## Errata

Departures found during implementation are listed here with their ruling numbers, as in the Phase 0 plan. Empty until implementation starts.
