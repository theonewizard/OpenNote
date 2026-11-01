"""Pull cursors: opaque to clients, `(protocol version, vault, seq)` to the server
(sync protocol §2.1, §12)."""

import base64
import struct
import uuid

PROTOCOL_VERSION = 1
# Prototype retention in sequence numbers: the simulation cannot wait 90 days and no
# decision may read a clock (I6). The production rule in days is Phase 5 (P5-07).
RETENTION_SEQ_WINDOW = 100_000
_FORMAT = ">B16sQ"


class CursorExpired(Exception):
    """The cursor is older than the tombstone retention window: run a full reconcile."""


def encode_cursor(vault_id: uuid.UUID, seq: int) -> str:
    raw = struct.pack(_FORMAT, PROTOCOL_VERSION, vault_id.bytes, seq)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor(cursor: str, vault_id: uuid.UUID) -> int:
    """The cursor's seq. ValueError when it is malformed, of another protocol version or
    of another vault."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        version, vault, seq = struct.unpack(_FORMAT, raw)
    except ValueError, struct.error:
        raise ValueError("malformed cursor") from None
    if version != PROTOCOL_VERSION or vault != vault_id.bytes:
        raise ValueError("cursor does not belong to this vault or protocol version")
    return int(seq)
