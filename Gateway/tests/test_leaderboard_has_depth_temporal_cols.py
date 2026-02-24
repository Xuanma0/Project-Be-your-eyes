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


def _set_depth_temporal_quality(
    report_path: Path,
    *,
    jitter_p90: float,
    flicker_mean: float,
    drift_p90: float,
    diversity: int,
) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        payload = {}
    quality = payload.get("quality")
    if not isinstance(quality, dict):
        quality = {}
    quality["depthTemporal"] = {
        "present": True,
        "framesTotal": 4,
        "framesWithDepth": 4,
        "coverage": 1.0,
        "jitterAbs": {"count": 3, "p50": max(0.0, jitter_p90 / 2.0), "p90": jitter_p90, "max": jitter_p90},
        "flickerRateNear": {
            "count": 3,
            "mean": flicker_mean,
            "p90": min(1.0, flicker_mean + 0.05),
            "max": min(1.0, flicker_mean + 0.1),
        },
        "scaleDriftProxy": {"count": 3, "p90": drift_p90, "max": drift_p90},
        "refViewStrategyDiversityCount": int(diversity),
    }
    payload["quality"] = quality
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_leaderboard_has_depth_temporal_cols() -> None:
    with TestClient(app) as client:
        stable_id, stable_dir = _upload(client, "run_package_min", "depth_temporal_stable")
        noisy_id, noisy_dir = _upload(client, "run_package_min", "depth_temporal_noisy")

        _set_depth_temporal_quality(
            stable_dir / "report.json",
            jitter_p90=0.02,
            flicker_mean=0.01,
            drift_p90=0.02,
            diversity=1,
        )
        _set_depth_temporal_quality(
            noisy_dir / "report.json",
            jitter_p90=0.45,
            flicker_mean=0.31,
            drift_p90=0.40,
            diversity=3,
        )

        resp = client.get(
            "/api/run_packages",
            params={"sort": "depth_jitter_p90", "order": "asc", "limit": 100},
        )
        assert resp.status_code == 200, resp.text
        items = resp.json().get("items", [])
        stable = next((item for item in items if item.get("runId") == stable_id), None)
        noisy = next((item for item in items if item.get("runId") == noisy_id), None)
        assert stable is not None
        assert noisy is not None
        assert float(stable.get("depth_jitter_p90", 0.0) or 0.0) == 0.02
        assert float(noisy.get("depth_jitter_p90", 0.0) or 0.0) == 0.45
        assert items.index(stable) < items.index(noisy)

        filtered = client.get(
            "/api/run_packages",
            params={
                "max_depth_jitter_p90": 0.1,
                "max_depth_flicker_mean": 0.1,
                "max_depth_scale_drift_p90": 0.1,
                "limit": 100,
            },
        )
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(item.get("runId") == stable_id for item in filtered_items)
        assert not any(item.get("runId") == noisy_id for item in filtered_items)

        page = client.get("/runs", params={"sort": "depth_jitter_p90", "order": "asc"})
        assert page.status_code == 200, page.text
        assert "Depth Jitter p90(m)" in page.text
        assert "Depth Flicker Mean" in page.text
        assert "Depth ScaleDrift p90(m)" in page.text
        assert "Depth RefView Diversity" in page.text

        shutil.rmtree(stable_dir, ignore_errors=True)
        shutil.rmtree(noisy_dir, ignore_errors=True)
