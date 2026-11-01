"""The shared path rules are public metadata (API contract §2)."""

from app.vaults.paths import PATH_RULES


def test_path_rules_endpoint_is_keyless(client):
    response = client.get("/api/v1/meta/path-rules")
    assert response.status_code == 200
    assert response.json() == PATH_RULES


def test_path_rules_state_the_limits():
    assert PATH_RULES["max_segment_bytes"] == 255
    assert PATH_RULES["max_path_bytes"] == 1024
    assert PATH_RULES["unicode_normalization"] == "NFC"
    assert "CON" in PATH_RULES["reserved_names"]
