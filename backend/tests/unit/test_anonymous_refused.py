"""The published v1 contract: every route outside the keyless list refuses anonymous callers."""

from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient

from app.api.main import KEYLESS_ROUTES, create_app
from tests.conftest import placeholder_settings


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
