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


def _set_slam_error(report_path: Path, *, ate: float, rpe: float) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        payload = {}
    quality = payload.get("quality")
    if not isinstance(quality, dict):
        quality = {}
    quality["slamError"] = {
        "present": True,
        "trajLabel": "online",
        "alignMode": "se3",
        "ate_rmse_m": ate,
        "rpe_trans_rmse_m": rpe,
        "coverage": {"pairsMatched": 3, "totalGt": 3, "totalPred": 3, "ratio": 1.0},
        "source": "gt/slam_gt_tum.txt",
    }
    payload["quality"] = quality
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_leaderboard_has_slam_error_cols() -> None:
    with TestClient(app) as client:
        better_id, better_dir = _upload(client, "run_package_min", "slam_error_better")
        worse_id, worse_dir = _upload(client, "run_package_min", "slam_error_worse")

        _set_slam_error((better_dir / "report.json"), ate=0.08, rpe=0.05)
        _set_slam_error((worse_dir / "report.json"), ate=0.30, rpe=0.22)

        resp = client.get("/api/run_packages", params={"sort": "slam_ate_rmse", "order": "asc", "limit": 100})
        assert resp.status_code == 200, resp.text
        items = resp.json().get("items", [])
        better = next((item for item in items if item.get("runId") == better_id), None)
        worse = next((item for item in items if item.get("runId") == worse_id), None)
        assert better is not None
        assert worse is not None
        assert float(better.get("slam_ate_rmse", 0.0) or 0.0) == 0.08
        assert float(worse.get("slam_rpe_trans_rmse", 0.0) or 0.0) == 0.22
        assert items.index(better) < items.index(worse)

        filtered = client.get("/api/run_packages", params={"max_slam_ate_rmse": 0.1, "limit": 100})
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(item.get("runId") == better_id for item in filtered_items)
        assert not any(item.get("runId") == worse_id for item in filtered_items)

        shutil.rmtree(better_dir, ignore_errors=True)
        shutil.rmtree(worse_dir, ignore_errors=True)

