"""JSON log lines on stdout, tagged with the request ID and with sensitive values redacted."""

import json
import logging
import sys
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, TextIO

REDACTED = "<redacted>"
SENSITIVE_KEY_PARTS = ("authorization", "cookie", "token", "password", "secret")

# Set by the request-ID middleware for the duration of each request.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_HANDLER_NAME = "opennote-json"
_RECORD_ATTRIBUTES = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def configure_logging(level: str, stream: TextIO | None = None) -> None:
    """Log JSON lines to `stream` (default stdout) from the root logger; a repeat call
    replaces the handler."""
    handler = logging.StreamHandler(sys.stdout if stream is None else stream)
    handler.set_name(_HANDLER_NAME)
    handler.addFilter(_tag_request_id)
    handler.addFilter(_redact_record)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for old in [h for h in root.handlers if h.get_name() == _HANDLER_NAME]:
        root.removeHandler(old)
        old.close()
    root.addHandler(handler)
    root.setLevel(level)


def _tag_request_id(record: logging.LogRecord) -> bool:
    """Tag the record with the current request's ID unless the caller passed one."""
    if record.__dict__.get("request_id") is None:
        record.__dict__["request_id"] = request_id_var.get()
    return True


def _redact_record(record: logging.LogRecord) -> bool:
    """Replace values of sensitive keys in `extra` fields, dict messages and format args.

    Keys are matched, not values: a secret passed as a plain positional argument or
    carried in exception text (exc_info) is not redacted here.
    """
    for key, value in list(record.__dict__.items()):
        if key not in _RECORD_ATTRIBUTES:
            record.__dict__[key] = _redact(key, value)
    if isinstance(record.msg, Mapping):
        record.msg = _redact(None, record.msg)
    if record.args:
        record.args = _redact(None, record.args)
    return True


def _redact(key: object, value: Any) -> Any:
    if isinstance(key, str) and any(part in key.lower() for part in SENSITIVE_KEY_PARTS):
        return REDACTED
    if isinstance(value, Mapping):
        return {k: _redact(k, v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        items = [_redact(None, item) for item in value]
        return items if isinstance(value, list) else tuple(items)
    return value


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, msg, request_id, extras, exc."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RECORD_ATTRIBUTES and key != "request_id"
        }
        entry |= {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.msg if isinstance(record.msg, Mapping) else record.getMessage(),
        }
        if request_id := record.__dict__.get("request_id"):
            entry["request_id"] = request_id
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)
