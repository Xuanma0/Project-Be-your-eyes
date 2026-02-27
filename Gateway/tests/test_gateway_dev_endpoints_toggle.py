from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(autouse=True)
def _clean_hardening_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BYES_GATEWAY_PROFILE", raising=False)
    monkeypatch.delenv("BYES_GATEWAY_DEV_ENDPOINTS_ENABLED", raising=False)
    monkeypatch.delenv("BYES_GATEWAY_RUNPACKAGE_UPLOAD_ENABLED", raising=False)
    monkeypatch.delenv("BYES_GATEWAY_ALLOW_LOCAL_RUNPACKAGE_PATH", raising=False)


def _assert_disabled(status_code: int) -> None:
    assert status_code in {403, 404}


def _zip_bytes() -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", "{}")
    return payload.getvalue()


def test_dev_endpoints_disabled_by_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYES_GATEWAY_DEV_ENDPOINTS_ENABLED", "0")
    with TestClient(app) as client:
        mock_event = client.get("/api/mock_event")
        fault_set = client.post("/api/fault/set", json={"tool": "mock_risk", "mode": "timeout"})
        fault_clear = client.post("/api/fault/clear")
        dev_reset = client.post("/api/dev/reset")
        dev_intent = client.post("/api/dev/intent", json={"kind": "none"})
        dev_crosscheck = client.post("/api/dev/crosscheck", json={})
        dev_performance = client.post("/api/dev/performance", json={})
    _assert_disabled(mock_event.status_code)
    _assert_disabled(fault_set.status_code)
    _assert_disabled(fault_clear.status_code)
    _assert_disabled(dev_reset.status_code)
    _assert_disabled(dev_intent.status_code)
    _assert_disabled(dev_crosscheck.status_code)
    _assert_disabled(dev_performance.status_code)


def test_dev_endpoints_disabled_by_hardened_profile_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYES_GATEWAY_PROFILE", "hardened")
    monkeypatch.delenv("BYES_GATEWAY_DEV_ENDPOINTS_ENABLED", raising=False)
    with TestClient(app) as client:
        response = client.get("/api/mock_event")
    _assert_disabled(response.status_code)


def test_dev_endpoints_enabled_keeps_mock_event_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYES_GATEWAY_DEV_ENDPOINTS_ENABLED", "1")
    with TestClient(app) as client:
        response = client.get("/api/mock_event")
    assert response.status_code == 200, response.text


def test_run_package_upload_disabled_by_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYES_GATEWAY_RUNPACKAGE_UPLOAD_ENABLED", "0")
    with TestClient(app) as client:
        response = client.post(
            "/api/run_package/upload",
            files={"file": ("sample.zip", _zip_bytes(), "application/zip")},
        )
    _assert_disabled(response.status_code)


def test_plan_rejects_local_path_when_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fixture_src = Path(__file__).resolve().parent / "fixtures" / "run_package_with_risk_gt_and_pov_min"
    run_pkg = tmp_path / "run_package_with_risk_gt_and_pov_min"
    shutil.copytree(fixture_src, run_pkg)

    monkeypatch.setenv("BYES_GATEWAY_ALLOW_LOCAL_RUNPACKAGE_PATH", "0")
    with TestClient(app) as client:
        response = client.post("/api/plan", json={"runPackage": str(run_pkg), "frameSeq": 1})
    _assert_disabled(response.status_code)
