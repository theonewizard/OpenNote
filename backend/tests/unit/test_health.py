"""The liveness probe answers without credentials. Readiness needs PostgreSQL, Valkey and
the data directories, so it is tested in tests/integration/test_readyz.py."""


def test_healthz_is_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
