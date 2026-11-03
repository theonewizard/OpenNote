"""The content-addressed history store (storage contract §7)."""

import hashlib
import json
import uuid

import pytest

from app.sync.history import HistoryCorrupt, HistoryStore, RevisionLogEntry


@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path, uuid.uuid7())


def entry(seq: int, committed_at: str = "2026-11-01T20:00:00+00:00") -> RevisionLogEntry:
    return RevisionLogEntry(
        seq=seq,
        file_id=uuid.uuid7(),
        revision=seq,
        path=f"n{seq}.md",
        kind="note",
        content_hash="sha256:" + "0" * 64,
        deleted=False,
        device_id="dev-1",
        op="update",
        committed_at=committed_at,
    )


def objects(store):
    return [p for p in (store.root / "objects").rglob("*") if p.is_file()]


def test_put_get_roundtrip_and_dedup(store):
    data = b"# note\r\nbytes\xff\n"
    digest = store.put(data)
    assert digest == "sha256:" + hashlib.sha256(data).hexdigest()
    [obj] = objects(store)
    assert obj.relative_to(store.root / "objects").as_posix() == f"{digest[7:9]}/{digest[9:]}"
    mtime = obj.stat().st_mtime_ns
    assert store.put(data) == digest
    assert objects(store) == [obj] and obj.stat().st_mtime_ns == mtime
    assert store.get(digest) == data
    assert not [p for p in store.root.rglob("*") if p.name.endswith(".tmp")]


def test_get_detects_corruption(store):
    digest = store.put(b"original")
    [obj] = objects(store)
    other = HistoryStore(store.root.parent, uuid.uuid7())
    obj.write_bytes((other.root / "objects").joinpath(*_rel(other.put(b"tampered"))).read_bytes())
    with pytest.raises(HistoryCorrupt):
        store.get(digest)
    obj.write_bytes(b"not zstd at all")
    with pytest.raises(HistoryCorrupt):
        store.get(digest)


def _rel(digest):
    return digest[7:9], digest[9:]


@pytest.mark.parametrize("bad", ["../../etc/passwd", "sha256:XYZ", "md5:" + "0" * 32])
def test_get_refuses_malformed_hashes(store, bad):
    with pytest.raises(ValueError):
        store.get(bad)


def test_missing_object_raises_file_not_found(store):
    with pytest.raises(FileNotFoundError):
        store.get("sha256:" + "a" * 64)


def test_objects_are_compressed(store):
    data = b"- [ ] the same task line over and over\n" * (1024 * 1024 // 39)
    store.put(data)
    [obj] = objects(store)
    assert obj.stat().st_size < 100 * 1024


def test_log_roundtrip_by_month(store):
    entries = [entry(1), entry(2, "2026-12-01T00:00:00+00:00"), entry(3)]
    for e in entries:
        store.append_log(e)
    assert sorted(p.name for p in (store.root / "log").iterdir()) == [
        "2026-11.jsonl",
        "2026-12.jsonl",
    ]
    assert sorted(store.read_log(), key=lambda e: e.seq) == entries


def test_log_survives_torn_last_line(store):
    store.append_log(entry(1))
    store.append_log(entry(2))
    log = store.root / "log" / "2026-11.jsonl"
    log.write_bytes(log.read_bytes() + b'{"seq": 3, "file_')
    assert [e.seq for e in store.read_log()] == [1, 2]
    store.append_log(entry(4))  # a later append after a torn tail still parses
    assert [e.seq for e in store.read_log()] == [1, 2, 4]


def test_log_corruption_mid_file_raises(store):
    store.append_log(entry(1))
    log = store.root / "log" / "2026-11.jsonl"
    log.write_bytes(b"garbage\n" + log.read_bytes())
    with pytest.raises(HistoryCorrupt):
        list(store.read_log())


def test_log_lines_are_json(store):
    store.append_log(entry(1))
    line = (store.root / "log" / "2026-11.jsonl").read_text().splitlines()[0]
    assert json.loads(line)["seq"] == 1
