from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_capabilities_v504_feature_flags_and_reasons(monkeypatch) -> None:
    monkeypatch.setenv("BYES_ENABLE_ASR", "1")
    monkeypatch.setenv("BYES_ASR_BACKEND", "mock")
    monkeypatch.setenv("BYES_ENABLE_PYSLAM_REALTIME", "1")
    monkeypatch.delenv("BYES_PYSLAM_ROOT", raising=False)

    with TestClient(app) as client:
        response = client.get("/api/capabilities")
        assert response.status_code == 200
        body = response.json()

    features = body.get("features", {})
    assert features.get("visionHud") is True
    assert features.get("assetEndpoint") is True
    assert features.get("segMaskAsset") is True
    assert features.get("depthMapAsset") is True
    assert features.get("asr") is True
    assert "pyslamRealtime" in features

    providers = body.get("available_providers", {})
    assert isinstance(providers, dict)
    assert isinstance(providers.get("asr", {}).get("reason"), str)
    assert isinstance(providers.get("pyslamRealtime", {}).get("reason"), str)
    for name in ("ocr", "risk", "det", "depth", "seg", "slam"):
        reason = providers.get(name, {}).get("reason")
        assert isinstance(reason, str)
        assert reason != ""
