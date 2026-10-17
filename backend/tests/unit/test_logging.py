"""JSON log lines: request ID, exceptions and redaction of sensitive values."""

import json
import logging

import pytest

from app.core.logging import configure_logging, request_id_var


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
                "context": {"user": "ada", "api_token": "t0ken"},
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
    for key in ("Authorization", "session_cookie", "refresh_token", "client_secret"):
        assert line[key] == "<redacted>"
    assert line["context"] == {"user": "ada", "api_token": "<redacted>"}
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
