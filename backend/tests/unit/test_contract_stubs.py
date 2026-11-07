"""The published v1 contract before its code: every route refuses anonymous callers, and
the keyless login routes answer 501 until P2-02 lands."""

from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient

from app.api.main import KEYLESS_ROUTES, create_app
from tests.conftest import placeholder_settings

PKCE = "a" * 43


def test_every_v1_route_outside_the_keyless_list_refuses_anonymous_callers():
    app = create_app(placeholder_settings())
    client = TestClient(app)
    checked = 0
    for route in iter_route_contexts(app.routes):
        if not isinstance(route.original_route, APIRoute) or "/api/v1/meta" in route.path:
            continue
        for method in route.methods or ():
            if (method, route.path) in KEYLESS_ROUTES or not route.path.startswith("/api/v1"):
                continue
            path = route.path.replace("{", "").replace("}", "")  # any segment will do
            path = path.replace("_id", "").replace("provider", "x")
            response = client.request(method, path)
            assert response.status_code == 401, (method, route.path)
            checked += 1
    assert checked > 30


def test_keyless_login_routes_are_not_implemented_yet():
    client = TestClient(create_app(placeholder_settings()))
    login = client.post("/api/v1/auth/login", json={"username": "a", "password": "b"})
    assert login.status_code == 501
    assert login.json()["type"] == "https://opennote.dev/problems/not-implemented"
    token = client.post(
        "/api/v1/auth/token", data={"grant_type": "refresh_token", "client_id": "web"}
    )
    assert token.status_code == 501
