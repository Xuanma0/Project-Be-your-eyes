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


def _set_slam_alignment(report_path: Path, *, residual_p90: int, mode: str) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        payload = {}
    quality = payload.get("quality")
    if not isinstance(quality, dict):
        quality = {}
    quality["slam"] = {
        "present": True,
        "framesTotal": 2,
        "framesWithGt": 2,
        "framesWithPred": 2,
        "coverage": 1.0,
        "tracking": {"trackingRate": 1.0, "lostRate": 0.0, "relocalizedCount": 0, "longestLostStreak": 0, "topLostFrames": []},
        "latencyMs": {"count": 2, "p50": 10, "p90": 20, "max": 25},
        "alignment": {
            "present": True,
            "mode": mode,
            "matched": 2,
            "unmatched": 0,
            "residualMs": {"p50": max(0, residual_p90 // 2), "p90": residual_p90, "max": residual_p90 + 5},
            "a": 1.0,
            "b": 0.0,
        },
    }
    payload["quality"] = quality
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_leaderboard_has_slam_alignment_cols() -> None:
    with TestClient(app) as client:
        better_run_id, better_dir = _upload(client, "run_package_min", "slam_align_better_case")
        worse_run_id, worse_dir = _upload(client, "run_package_min", "slam_align_worse_case")

        _set_slam_alignment((better_dir / "report.json"), residual_p90=8, mode="fit_linear")
        _set_slam_alignment((worse_dir / "report.json"), residual_p90=42, mode="nearest")

        resp = client.get("/api/run_packages", params={"sort": "slam_align_residual_p90", "order": "asc", "limit": 100})
        assert resp.status_code == 200, resp.text
        items = resp.json().get("items", [])
        better = next((item for item in items if item.get("runId") == better_run_id), None)
        worse = next((item for item in items if item.get("runId") == worse_run_id), None)
        assert better is not None
        assert worse is not None
        assert int(better.get("slam_align_residual_p90", 0) or 0) == 8
        assert str(better.get("slam_align_mode", "")) == "fit_linear"
        assert int(worse.get("slam_align_residual_p90", 0) or 0) == 42
        assert items.index(better) < items.index(worse)

        filtered = client.get("/api/run_packages", params={"max_slam_align_residual_p90": 10, "limit": 100})
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(item.get("runId") == better_run_id for item in filtered_items)
        assert not any(item.get("runId") == worse_run_id for item in filtered_items)

        shutil.rmtree(better_dir, ignore_errors=True)
        shutil.rmtree(worse_dir, ignore_errors=True)
