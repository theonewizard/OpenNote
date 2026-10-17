"""RFC 9457 problem responses, request IDs and the log lines that carry them."""

import json
import logging
import uuid

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_principal
from app.core.logging import configure_logging, request_id_var
from tests.conftest import as_test_user

PROBLEMS = "https://opennote.dev/problems/"


def test_unhandled_exception_returns_generic_problem(client_with_failing_route, auth):
    r = client_with_failing_route.get("/api/v1/boom", headers=auth)
    assert r.status_code == 500
    assert r.headers["content-type"] == "application/problem+json"
    assert "Traceback" not in r.text and "boom-secret" not in r.text


def test_unhandled_exception_is_logged_with_the_request_id(client_with_failing_route, auth, caplog):
    r = client_with_failing_route.get("/api/v1/boom", headers=auth)
    assert r.json() == {
        "type": PROBLEMS + "internal-error",
        "title": "Internal error",
        "status": 500,
        "detail": "An internal error occurred. The request ID is in the X-Request-ID header.",
        "instance": "/api/v1/boom",
    }
    [record] = [rec for rec in caplog.records if rec.levelno >= logging.ERROR]
    assert record.request_id == r.headers["x-request-id"]
    assert str(record.exc_info[1]) == "boom-secret"


def test_validation_error_points_at_the_field_without_echoing_input(build_app, auth):
    router = APIRouter(dependencies=[Depends(get_current_principal)])

    @router.get("/api/v1/items")
    def items(limit: int):
        return {"limit": limit}

    client = TestClient(as_test_user(build_app(router)))
    r = client.get("/api/v1/items", params={"limit": "hunter2"}, headers=auth)
    assert r.status_code == 422
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["type"] == PROBLEMS + "validation-error"
    assert body["instance"] == "/api/v1/items"
    assert [error["pointer"] for error in body["errors"]] == ["/query/limit"]
    assert "hunter2" not in r.text


def test_unknown_path_is_a_404_problem(client):
    r = client.get("/api/v1/nowhere")
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json() == {
        "type": PROBLEMS + "http-error",
        "title": "HTTP error",
        "status": 404,
        "detail": "Not Found",
        "instance": "/api/v1/nowhere",
    }


def test_http_error_keeps_its_headers(client):
    r = client.post("/healthz")
    assert r.status_code == 405
    assert r.headers["allow"] == "GET"
    assert r.json()["type"] == PROBLEMS + "http-error"


def test_request_id_is_generated_and_echoed(client):
    r = client.get("/healthz")
    assert uuid.UUID(r.headers["x-request-id"]).version == 4


def test_valid_inbound_request_id_is_kept(client):
    r = client.get("/healthz", headers={"X-Request-ID": "client-req 42"})
    assert r.headers["x-request-id"] == "client-req 42"


@pytest.mark.parametrize("inbound", ["x" * 129, "bell\x07", "déjà".encode()])
def test_invalid_inbound_request_id_is_replaced(client, inbound):
    r = client.get("/healthz", headers={"X-Request-ID": inbound})
    assert uuid.UUID(r.headers["x-request-id"]).version == 4


def test_request_id_is_set_for_logging_during_the_request(build_app, auth):
    router = APIRouter(dependencies=[Depends(get_current_principal)])

    @router.get("/api/v1/current-request-id")
    def current_request_id():
        return {"request_id": request_id_var.get()}

    client = TestClient(as_test_user(build_app(router)))
    r = client.get("/api/v1/current-request-id", headers={**auth, "X-Request-ID": "req-42"})
    assert r.json() == {"request_id": "req-42"}


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
