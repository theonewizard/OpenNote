"""RFC 9457 problem responses and request IDs."""

import logging
import uuid

import pytest
from fastapi import APIRouter, Depends, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_principal
from app.core.logging import request_id_var
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


def protected_client(build_app, router):
    return TestClient(as_test_user(build_app(router)))


def test_http_exception_detail_is_replaced_by_the_status_phrase(build_app, auth):
    router = APIRouter(dependencies=[Depends(get_current_principal)])

    @router.get("/api/v1/refuse")
    def refuse():
        raise HTTPException(
            400, detail="secret-path /srv/vault/xyz hunter2", headers={"X-Probe": "kept"}
        )

    r = protected_client(build_app, router).get("/api/v1/refuse", headers=auth)
    assert r.status_code == 400
    assert r.headers["content-type"] == "application/problem+json"
    assert r.headers["x-probe"] == "kept"
    assert r.json()["detail"] == "Bad Request"
    assert "/srv/vault" not in r.text and "hunter2" not in r.text


def test_http_exception_without_a_body_status_gets_an_empty_response(build_app, auth):
    router = APIRouter(dependencies=[Depends(get_current_principal)])

    @router.get("/api/v1/unchanged")
    def unchanged():
        raise HTTPException(304, headers={"ETag": '"7"'})

    r = protected_client(build_app, router).get("/api/v1/unchanged", headers=auth)
    assert r.status_code == 304
    assert r.content == b""
    assert "content-type" not in r.headers
    assert r.headers["etag"] == '"7"'


def test_validation_pointer_escapes_slash_and_tilde(build_app, auth):
    class Payload(BaseModel):
        value: int = Field(alias="a/b~c")

    router = APIRouter(dependencies=[Depends(get_current_principal)])

    @router.post("/api/v1/payload")
    def payload(body: Payload):
        return {}

    r = protected_client(build_app, router).post(
        "/api/v1/payload", json={"a/b~c": "not-a-number"}, headers=auth
    )
    assert r.status_code == 422
    assert [error["pointer"] for error in r.json()["errors"]] == ["/body/a~1b~0c"]


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
