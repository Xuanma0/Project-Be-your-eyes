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


def _set_costmap_fused_quality(
    report_path: Path,
    *,
    coverage: float,
    latency_p90: int,
    iou_p90: float,
    flicker_mean: float,
    shift_used_rate: float,
) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        payload = {}
    quality = payload.get("quality")
    if not isinstance(quality, dict):
        quality = {}
    quality["costmapFused"] = {
        "present": True,
        "framesTotal": 2,
        "framesWithFused": 2,
        "coverage": coverage,
        "latencyMs": {"count": 2, "p50": max(1, latency_p90 // 2), "p90": latency_p90, "max": latency_p90 + 10},
        "dynamicFilteredRate": {"mean": 0.2, "p90": 0.3},
        "densityMean": {"mean": 0.2, "p90": 0.3},
        "stability": {
            "iouPrevMean": max(0.0, iou_p90 - 0.1),
            "iouPrevP90": iou_p90,
            "flickerRatePrevMean": flicker_mean,
            "flickerRatePrevP90": min(1.0, flicker_mean + 0.05),
            "hotspotCountMean": 5.0,
            "hotspotCountP90": 6.0,
        },
        "shiftUsedRate": shift_used_rate,
    }
    payload["quality"] = quality
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_leaderboard_has_costmap_fused_cols() -> None:
    with TestClient(app) as client:
        fast_id, fast_dir = _upload(client, "run_package_min", "costmap_fused_fast_case")
        slow_id, slow_dir = _upload(client, "run_package_min", "costmap_fused_slow_case")

        _set_costmap_fused_quality(
            fast_dir / "report.json",
            coverage=1.0,
            latency_p90=25,
            iou_p90=0.92,
            flicker_mean=0.08,
            shift_used_rate=0.5,
        )
        _set_costmap_fused_quality(
            slow_dir / "report.json",
            coverage=0.6,
            latency_p90=130,
            iou_p90=0.41,
            flicker_mean=0.31,
            shift_used_rate=0.1,
        )

        resp = client.get("/api/run_packages", params={"sort": "costmap_fused_iou_p90", "order": "desc", "limit": 100})
        assert resp.status_code == 200, resp.text
        items = resp.json().get("items", [])
        fast = next((row for row in items if row.get("runId") == fast_id), None)
        slow = next((row for row in items if row.get("runId") == slow_id), None)
        assert fast is not None
        assert slow is not None
        assert float(fast.get("costmap_fused_iou_p90", 0.0) or 0.0) == 0.92
        assert float(slow.get("costmap_fused_iou_p90", 0.0) or 0.0) == 0.41
        assert items.index(fast) < items.index(slow)

        filtered = client.get(
            "/api/run_packages",
            params={
                "min_costmap_fused_coverage": 0.9,
                "max_costmap_fused_latency_p90": 40,
                "min_costmap_fused_iou_p90": 0.8,
                "max_costmap_fused_flicker_rate_mean": 0.1,
                "limit": 100,
            },
        )
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(row.get("runId") == fast_id for row in filtered_items)
        assert not any(row.get("runId") == slow_id for row in filtered_items)

        page = client.get("/runs", params={"sort": "costmap_fused_iou_p90", "order": "desc"})
        assert page.status_code == 200, page.text
        assert "Costmap Fused Coverage" in page.text
        assert "Costmap Fused IoU p90" in page.text

        shutil.rmtree(fast_dir, ignore_errors=True)
        shutil.rmtree(slow_dir, ignore_errors=True)
