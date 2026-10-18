"""Server metadata is public: clients read it before they log in."""

from app.api.meta import app_version


def test_meta_reports_versions(client):
    assert client.get("/api/v1/meta").json() == {
        "server_version": app_version(),
        "api_versions": ["v1"],
        "sync_protocol_versions": [1],
        "login_methods": [],
    }
