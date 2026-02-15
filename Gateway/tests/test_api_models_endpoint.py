from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_api_models_endpoint_returns_manifest() -> None:
    with TestClient(app) as client:
        response = client.get("/api/models")
        assert response.status_code == 200, response.text
        payload = response.json()

    assert payload.get("schemaVersion") == "byes.models.v1"
    summary = payload.get("summary", {})
    assert isinstance(summary, dict)
    components_total = int(summary.get("componentsTotal", 0) or 0)
    enabled_total = int(summary.get("enabledTotal", 0) or 0)
    assert components_total >= 1
    assert 0 <= enabled_total <= components_total
    assert int(summary.get("missingRequiredTotal", 0) or 0) >= 0

    components = payload.get("components", [])
    assert isinstance(components, list)
    assert any(str(item.get("name", "")).strip() == "seg" for item in components if isinstance(item, dict))
