"""The OpenAPI document that scripts/gen-openapi.sh exports and the clients are generated from."""

from typing import Any

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from app import __version__
from app.api.main import create_app
from app.api.openapi import duplicate_operation_ids
from app.auth.dependencies import get_current_principal
from tests.conftest import as_test_user, placeholder_settings

PROBLEM_CONTENT = {
    "application/problem+json": {"schema": {"$ref": "#/components/schemas/ProblemDetails"}}
}
JSON_TYPES = {"string": str, "integer": int}


def openapi() -> dict[str, Any]:
    return create_app(placeholder_settings()).openapi()


def assert_fits_problem_schema(body: dict[str, Any], *extensions: str) -> None:
    schema = openapi()["components"]["schemas"]["ProblemDetails"]
    assert set(schema["required"]) <= body.keys()
    assert body.keys() - schema["properties"].keys() == set(extensions)
    for name, member in schema["properties"].items():
        if name in body:
            assert isinstance(body[name], JSON_TYPES[member["type"]])


def list_items_route(router: APIRouter, path: str) -> None:
    @router.get(path)
    def list_items(limit: int) -> list[int]:
        return [limit]


def test_info_names_the_api_and_its_version_without_servers():
    document = openapi()
    assert document["info"] == {"title": "OpenNote API", "version": __version__}
    assert "servers" not in document


def test_operation_ids_are_the_endpoint_names():
    operation_ids = {
        (method, path): operation["operationId"]
        for path, operations in openapi()["paths"].items()
        for method, operation in operations.items()
    }
    assert operation_ids == {
        ("get", "/healthz"): "healthz",
        ("get", "/readyz"): "readyz",
        ("get", "/api/v1/meta"): "get_meta",
    }


def test_every_operation_answers_errors_with_problem_details():
    document = openapi()
    for operations in document["paths"].values():
        for operation in operations.values():
            assert operation["responses"]["default"]["content"] == PROBLEM_CONTENT
    schema = document["components"]["schemas"]["ProblemDetails"]
    assert schema["required"] == ["type", "title", "status"]
    assert schema["additionalProperties"] is True


def test_readyz_documents_its_503_probe_body():
    responses = openapi()["paths"]["/readyz"]["get"]["responses"]
    assert responses["503"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/ProbeStatus"}}
    }


def test_fastapis_own_422_body_is_not_documented(build_app):
    # Our 422 is a problem (the default response), not FastAPI's HTTPValidationError.
    router = APIRouter(dependencies=[Depends(get_current_principal)])
    list_items_route(router, "/api/v1/items")
    document = build_app(router).openapi()
    responses = document["paths"]["/api/v1/items"]["get"]["responses"]
    assert "422" not in responses
    assert responses["default"]["content"] == PROBLEM_CONTENT
    assert "HTTPValidationError" not in document["components"]["schemas"]


def test_a_404_problem_fits_the_documented_schema(client):
    assert_fits_problem_schema(client.get("/api/v1/nowhere").json())


def test_a_422_problem_fits_the_documented_schema(build_app, auth):
    router = APIRouter(dependencies=[Depends(get_current_principal)])
    list_items_route(router, "/api/v1/items")
    client = TestClient(as_test_user(build_app(router)))
    response = client.get("/api/v1/items", params={"limit": "many"}, headers=auth)
    assert response.status_code == 422
    assert_fits_problem_schema(response.json(), "errors")


def test_a_500_problem_fits_the_documented_schema(client_with_failing_route, auth):
    response = client_with_failing_route.get("/api/v1/boom", headers=auth)
    assert response.status_code == 500
    assert_fits_problem_schema(response.json())


def test_the_export_check_finds_operation_ids_used_twice(build_app):
    assert duplicate_operation_ids(openapi()) == []
    router = APIRouter(dependencies=[Depends(get_current_principal)])
    list_items_route(router, "/api/v1/items")
    list_items_route(router, "/api/v1/more-items")
    with pytest.warns(UserWarning, match="Duplicate Operation ID list_items"):
        document = build_app(router).openapi()  # FastAPI only warns
    assert duplicate_operation_ids(document) == ["list_items"]
