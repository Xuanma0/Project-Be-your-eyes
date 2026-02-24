from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


def _zip_fixture_bytes(fixture_name: str) -> bytes:
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / fixture_name
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in fixture_dir.rglob("*"):
            if item.is_file():
                zf.write(item, item.relative_to(fixture_dir))
    return buffer.getvalue()


def _upload(client: TestClient, fixture_name: str, scenario: str) -> tuple[str, Path]:
    payload = _zip_fixture_bytes(fixture_name)
    response = client.post(
        "/api/run_package/upload",
        files={"file": (f"{fixture_name}.zip", payload, "application/zip")},
        data={"scenarioTag": scenario},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return str(body["runId"]), Path(body["runDir"])


def _set_models_summary(report_path: Path, *, missing_required: int, enabled_total: int) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        payload = {}
    payload["models"] = {
        "present": True,
        "componentsTotal": 4,
        "enabledTotal": int(enabled_total),
        "missingRequiredTotal": int(missing_required),
        "missingRequiredTop": [],
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_models_cols() -> None:
    with TestClient(app) as client:
        better_id, better_dir = _upload(client, "run_package_min", "models_better")
        worse_id, worse_dir = _upload(client, "run_package_min", "models_worse")

        _set_models_summary(better_dir / "report.json", missing_required=0, enabled_total=3)
        _set_models_summary(worse_dir / "report.json", missing_required=2, enabled_total=3)

        resp = client.get("/api/run_packages", params={"sort": "models_missing_required", "order": "asc", "limit": 100})
        assert resp.status_code == 200, resp.text
        items = resp.json().get("items", [])
        better = next((item for item in items if item.get("runId") == better_id), None)
        worse = next((item for item in items if item.get("runId") == worse_id), None)
        assert better is not None
        assert worse is not None
        assert int(better.get("models_missing_required", 99)) == 0
        assert int(worse.get("models_missing_required", 0)) == 2
        assert items.index(better) < items.index(worse)

        filtered = client.get("/api/run_packages", params={"max_models_missing_required": 0, "limit": 100})
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(item.get("runId") == better_id for item in filtered_items)
        assert not any(item.get("runId") == worse_id for item in filtered_items)

        page = client.get("/runs", params={"sort": "models_missing_required", "order": "asc"})
        assert page.status_code == 200, page.text
        assert "Models Missing" in page.text
        assert "Models Enabled" in page.text

        shutil.rmtree(better_dir, ignore_errors=True)
        shutil.rmtree(worse_dir, ignore_errors=True)
