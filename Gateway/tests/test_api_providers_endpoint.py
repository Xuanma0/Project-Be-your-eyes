from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from main import app, gateway


def test_api_providers_shape() -> None:
    with TestClient(app) as client:
        response = client.get("/api/providers")
        assert response.status_code == 200
        body = response.json()
        assert body.get("ok") is True
        assert isinstance(body.get("providers"), dict)
        assert isinstance(body.get("enabledFlags"), dict)
        assert isinstance(body.get("runtimeOverrides"), dict)


def test_api_providers_overrides_det_enabled_and_backend() -> None:
    enabled_snapshot = deepcopy(gateway._runtime_target_enabled_overrides)  # noqa: SLF001
    backend_snapshot = deepcopy(gateway._provider_backend_overrides)  # noqa: SLF001
    updated_snapshot = gateway._providers_override_updated_ts_ms  # noqa: SLF001
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/providers/overrides",
                json={
                    "det": {
                        "enabled": False,
                        "backend": "yolo26",
                    }
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body.get("ok") is True
            providers = body.get("providers", {})
            det = providers.get("det", {})
            assert det.get("enabled") is False
            assert det.get("requestedBackend") == "yolo26"
    finally:
        gateway._runtime_target_enabled_overrides.clear()  # noqa: SLF001
        gateway._runtime_target_enabled_overrides.update(enabled_snapshot)  # noqa: SLF001
        gateway._provider_backend_overrides.clear()  # noqa: SLF001
        gateway._provider_backend_overrides.update(backend_snapshot)  # noqa: SLF001
        gateway._providers_override_updated_ts_ms = updated_snapshot  # noqa: SLF001
