"""The OpenAPI document that scripts/gen-openapi.sh exports and the clients are generated from."""

from typing import Any

from fastapi import APIRouter, Depends

from app import __version__
from app.api.main import create_app
from app.auth.dependencies import get_current_principal
from tests.conftest import test_settings

PROBLEM_CONTENT = {
    "application/problem+json": {"schema": {"$ref": "#/components/schemas/ProblemDetails"}}
}


def openapi() -> dict[str, Any]:
    return create_app(test_settings()).openapi()


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

    @router.get("/api/v1/items")
    def list_items(limit: int) -> list[int]:
        return [limit]

    document = build_app(router).openapi()
    responses = document["paths"]["/api/v1/items"]["get"]["responses"]
    assert "422" not in responses
    assert responses["default"]["content"] == PROBLEM_CONTENT
    assert "HTTPValidationError" not in document["components"]["schemas"]


def test_a_problem_response_fits_the_documented_schema(client):
    schema = openapi()["components"]["schemas"]["ProblemDetails"]
    body = client.get("/api/v1/nowhere").json()
    assert set(schema["required"]) <= body.keys() <= schema["properties"].keys()
    assert isinstance(body["status"], int)
