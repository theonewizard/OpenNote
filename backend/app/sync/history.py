"""The server's history store: every committed revision's bytes, content-addressed and
zstd-compressed, plus a JSONL revision log, outside the vault and outside PostgreSQL
(storage contract §7), so history can be rebuilt without the database.
"""

import dataclasses
import hashlib
import json
import os
import re
import secrets
import uuid
from collections.abc import Iterator
from compression import zstd
from dataclasses import dataclass
from pathlib import Path

_HASH = re.compile(r"sha256:[0-9a-f]{64}")


class HistoryCorrupt(Exception):
    """A stored object or log line does not match what was written."""


@dataclass(frozen=True)
class RevisionLogEntry:
    seq: int
    file_id: uuid.UUID
    revision: int
    path: str
    kind: str
    content_hash: str | None
    deleted: bool
    device_id: str
    op: str
    committed_at: str  # informational only (I6); also names the month's log file


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class HistoryStore:
    def __init__(self, history_root: Path, vault_id: uuid.UUID) -> None:
        self.root = history_root / str(vault_id)

    def _object(self, content_hash: str) -> Path:
        if not _HASH.fullmatch(content_hash):
            raise ValueError("not a sha256 content hash")
        return self.root / "objects" / content_hash[7:9] / content_hash[9:]

    def put(self, data: bytes) -> str:
        """Store `data` once and return its content hash."""
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        path = self._object(digest)
        if path.exists():
            return digest
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
        with open(tmp, "xb") as fh:
            fh.write(zstd.compress(data))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
        return digest

    def get(self, content_hash: str) -> bytes:
        """The bytes stored under `content_hash`; HistoryCorrupt if they do not match it."""
        compressed = self._object(content_hash).read_bytes()
        try:
            data = zstd.decompress(compressed)
        except zstd.ZstdError:
            raise HistoryCorrupt("history object is not valid zstd") from None
        if "sha256:" + hashlib.sha256(data).hexdigest() != content_hash:
            raise HistoryCorrupt("history object does not match its hash")
        return data

    def append_log(self, entry: RevisionLogEntry) -> None:
        """Append one JSON line to the month's log and fsync it. A torn last line (a crash
        mid-append, never acknowledged) is cut off first."""
        log_dir = self.root / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(dataclasses.asdict(entry), default=str, ensure_ascii=False) + "\n"
        path = log_dir / f"{entry.committed_at[:7]}.jsonl"
        with open(path, "a+b") as fh:
            fh.seek(0)
            content = fh.read()
            if content and not content.endswith(b"\n"):
                fh.truncate(content.rfind(b"\n") + 1)
            fh.write(line.encode())
            fh.flush()
            os.fsync(fh.fileno())

    def read_log(self) -> Iterator[RevisionLogEntry]:
        """Every entry, month by month in file order; a torn last line is skipped."""
        log_dir = self.root / "log"
        if not log_dir.is_dir():
            return
        for path in sorted(log_dir.glob("*.jsonl")):
            # The last piece is b"" after a final newline, or else a torn line.
            for line in path.read_bytes().split(b"\n")[:-1]:
                try:
                    data = json.loads(line)
                    data["file_id"] = uuid.UUID(data["file_id"])
                    yield RevisionLogEntry(**data)
                except ValueError, KeyError, TypeError:
                    raise HistoryCorrupt(f"bad revision log line in {path.name}") from None
