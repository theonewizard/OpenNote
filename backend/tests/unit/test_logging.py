"""JSON log lines: request ID, exceptions and redaction of sensitive values."""

import io
import json
import logging
from collections import namedtuple

import pytest

from app.core.logging import _redact, configure_logging, request_id_var


@pytest.fixture
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_log_lines_are_json_with_request_id_and_redacted_secrets(capsys, restore_root_logger):
    configure_logging("INFO")
    token = request_id_var.set("req-7")
    try:
        logging.getLogger("opennote.test").info(
            {"event": "login", "password": "hunter2"},
            extra={
                "Authorization": "Bearer abc",
                "session_cookie": "c00kie",
                "refresh_token": "t0ken",
                "client_secret": "s3cret",
                "api_key": "k3y",
                "context": {"user": "ada", "api_token": "t0ken", "X-API-Key": "k3y"},
                "user": "ada",
            },
        )
    finally:
        request_id_var.reset(token)
    line = json.loads(capsys.readouterr().out)
    assert line["level"] == "INFO"
    assert line["logger"] == "opennote.test"
    assert line["request_id"] == "req-7"
    assert line["msg"] == {"event": "login", "password": "<redacted>"}
    for key in ("Authorization", "session_cookie", "refresh_token", "client_secret", "api_key"):
        assert line[key] == "<redacted>"
    assert line["context"] == {"user": "ada", "api_token": "<redacted>", "X-API-Key": "<redacted>"}
    assert line["user"] == "ada"
    assert "ts" in line


def test_log_line_carries_the_exception(capsys, restore_root_logger):
    configure_logging("INFO")
    try:
        raise ValueError("kaput")
    except ValueError:
        logging.getLogger("opennote.test").exception("failed")
    line = json.loads(capsys.readouterr().out)
    assert line["msg"] == "failed"
    assert "request_id" not in line
    assert "ValueError: kaput" in line["exc"]


def test_reconfiguring_replaces_the_handler_and_level(capsys, restore_root_logger):
    configure_logging("INFO")
    configure_logging("WARNING")
    logging.getLogger("opennote.test").info("below the level")
    logging.getLogger("opennote.test").warning("once")
    assert [json.loads(line)["msg"] for line in capsys.readouterr().out.splitlines()] == ["once"]


def test_log_lines_go_to_the_given_stream_instead_of_stdout(capsys, restore_root_logger):
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    logging.getLogger("opennote.test").info("to the stream")
    assert json.loads(stream.getvalue())["msg"] == "to the stream"
    assert capsys.readouterr().out == ""


def log_line(capsys, *args, **kwargs):
    configure_logging("INFO")
    logging.getLogger("opennote.test").info(*args, **kwargs)
    return capsys.readouterr().out


def test_redaction_reaches_dicts_inside_lists_in_extras(capsys, restore_root_logger):
    out = log_line(capsys, "request", extra={"headers": [{"authorization": "Bearer LEAK1"}]})
    assert json.loads(out)["headers"] == [{"authorization": "<redacted>"}]
    assert "LEAK1" not in out


def test_redaction_reaches_dicts_inside_lists_in_dict_messages(capsys, restore_root_logger):
    out = log_line(capsys, {"items": [{"password": "LEAK3"}, ({"token": "LEAK4"},)]})
    assert json.loads(out)["msg"] == {
        "items": [{"password": "<redacted>"}, [{"token": "<redacted>"}]]
    }
    assert "LEAK3" not in out and "LEAK4" not in out


def test_redaction_reaches_mapping_format_arguments(capsys, restore_root_logger):
    out = log_line(capsys, "login %(user)s with %(password)s", {"user": "ada", "password": "LEAK5"})
    assert json.loads(out)["msg"] == "login ada with <redacted>"
    assert "LEAK5" not in out


def test_redaction_reaches_mappings_among_positional_arguments(capsys, restore_root_logger):
    out = log_line(capsys, "%s then %s", {"api_token": "LEAK6"}, "done")
    assert json.loads(out)["msg"] == "{'api_token': '<redacted>'} then done"
    assert "LEAK6" not in out


def test_redaction_ends_on_a_self_referencing_structure(capsys, restore_root_logger):
    loop = {"password": "LEAK7"}
    loop["self"] = loop
    out = log_line(capsys, "loop", extra={"loop": loop})
    assert "LEAK7" not in out
    nested = json.loads(out)["loop"]
    for _ in range(8):
        assert set(nested) == {"password", "self"}
        nested = nested["self"]
    assert nested == "<redacted>"  # the depth guard


class Pair(tuple):
    """A tuple subclass, as a library might put in a log record."""


def test_redaction_keeps_the_container_type_and_unchanged_objects():
    redacted = _redact(None, Pair(({"token": "LEAK8"}, "kept")))
    assert type(redacted) is Pair
    assert redacted == ({"token": "<redacted>"}, "kept")
    clean = Pair(({"user": "ada"}, "kept"))
    assert _redact(None, clean) is clean


One = namedtuple("One", ["body"])
Two = namedtuple("Two", ["body", "note"])


def test_redaction_rebuilds_a_namedtuple_field_by_field():
    # Fields are positional and carry no key, so the secret sits in a mapping in a field.
    one = _redact(None, One({"password": "LEAK9"}))
    assert type(one) is One
    assert one == One({"password": "<redacted>"})
    two = _redact(None, Two({"password": "LEAK10"}, "kept"))
    assert type(two) is Two
    assert two == Two({"password": "<redacted>"}, "kept")


def test_uvicorn_color_message_is_left_out(capsys, restore_root_logger):
    out = log_line(
        capsys,
        "Started server process [%d]",
        42,
        extra={"color_message": "Started server process [\x1b[36m%d\x1b[0m]"},
    )
    line = json.loads(out)
    assert line["msg"] == "Started server process [42]"
    assert "color_message" not in line
