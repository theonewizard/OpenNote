"""Deny by default: startup fails for any route without an auth dependency or keyless exemption."""

from typing import Annotated

import pytest
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from app.api import main
from app.api.main import KEYLESS_ROUTES, assert_routes_authenticated, create_app
from app.auth.dependencies import Principal, get_api_key, get_current_principal
from tests.conftest import as_test_user, test_settings


def test_unauthenticated_route_fails_startup(monkeypatch):
    rogue = APIRouter()

    @rogue.get("/api/v1/oops")
    def oops():
        return {}

    monkeypatch.setattr(main, "ROUTERS", [*main.ROUTERS, rogue])
    with pytest.raises(RuntimeError, match="/api/v1/oops"):
        create_app(test_settings())


def test_keyless_routes_are_exactly_the_documented_set():
    assert {p for _, p in KEYLESS_ROUTES} == {"/healthz", "/readyz", "/api/v1/meta"}


def test_routes_protected_by_either_auth_dependency_pass(build_app):
    router = APIRouter()

    @router.get("/api/v1/for-users", dependencies=[Depends(get_current_principal)])
    def for_users():
        return {}

    @router.get("/api/v1/for-automation", dependencies=[Depends(get_api_key)])
    def for_automation():
        return {}

    build_app(router)


def test_auth_dependency_deeper_in_the_tree_counts(build_app):
    async def current_user(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> Principal:
        return principal

    router = APIRouter()

    @router.get("/api/v1/me")
    def me(user: Annotated[Principal, Depends(current_user)]):
        return {}

    build_app(router)


def router_level_dependency():
    router = APIRouter(dependencies=[Depends(get_current_principal)])

    @router.get("/api/v1/router-level")
    def guarded():
        return {"ok": True}

    return router, "/api/v1/router-level"


def include_level_dependency():
    inner = APIRouter()

    @inner.get("/api/v1/include-level")
    def guarded():
        return {"ok": True}

    outer = APIRouter()
    outer.include_router(inner, dependencies=[Depends(get_current_principal)])
    return outer, "/api/v1/include-level"


def nested_include_with_outer_dependency():
    inner = APIRouter()

    @inner.get("/nested")
    def guarded():
        return {"ok": True}

    middle = APIRouter(prefix="/middle")
    middle.include_router(inner)
    outer = APIRouter(prefix="/api/v1/outer", dependencies=[Depends(get_current_principal)])
    outer.include_router(middle)
    return outer, "/api/v1/outer/middle/nested"


@pytest.mark.parametrize(
    "layout",
    [router_level_dependency, include_level_dependency, nested_include_with_outer_dependency],
)
def test_dependencies_from_routers_and_includes_count(build_app, layout):
    router, path = layout()
    app = build_app(router)
    assert assert_routes_authenticated(app) is None
    assert TestClient(app).get(path).status_code == 401
    assert TestClient(as_test_user(app)).get(path).json() == {"ok": True}


def test_frontend_routes_fail_startup(tmp_path):
    app = create_app(test_settings())
    app.frontend("/", directory=tmp_path)
    with pytest.raises(RuntimeError, match="frontend /"):
        assert_routes_authenticated(app)


def test_frontend_routes_of_an_included_router_fail_startup(build_app, tmp_path):
    router = APIRouter(prefix="/ui")
    router.frontend("/", directory=tmp_path)
    with pytest.raises(RuntimeError, match="frontend /ui"):
        build_app(router)


def test_error_names_every_offending_method_and_path(build_app):
    router = APIRouter()

    @router.post("/healthz")  # keyless only for GET
    def post_health():
        return {}

    @router.delete("/api/v1/also-oops")
    def also_oops():
        return {}

    with pytest.raises(RuntimeError) as e:
        build_app(router)
    assert "POST /healthz" in str(e.value)
    assert "DELETE /api/v1/also-oops" in str(e.value)
    assert "GET /healthz" not in str(e.value)


def test_route_the_guard_cannot_inspect_fails_startup(build_app):
    router = APIRouter()
    router.add_route("/raw", lambda request: PlainTextResponse("no auth here"))
    with pytest.raises(RuntimeError, match="/raw"):
        build_app(router)


@pytest.mark.parametrize(
    ("dependency", "headers"),
    [
        (get_current_principal, {}),
        (get_current_principal, {"Authorization": "Bearer any-token"}),
        (get_api_key, {}),
        (get_api_key, {"X-API-Key": "any-key"}),
    ],
)
def test_phase_0_rejects_every_credential_with_a_401_problem(build_app, dependency, headers):
    router = APIRouter()

    @router.get("/api/v1/private", dependencies=[Depends(dependency)])
    def private():
        return {"private": "leaked-payload"}

    response = TestClient(build_app(router)).get("/api/v1/private", headers=headers)
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["www-authenticate"] == "Bearer"
    body = response.json()
    assert body["type"] == "https://opennote.dev/problems/unauthenticated"
    assert body["status"] == 401
    assert body["instance"] == "/api/v1/private"
    assert "leaked-payload" not in response.text
