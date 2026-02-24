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
    shift_used_rate: float,
    shift_reject_rate: float,
    top_reason: str,
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
        "coverage": 1.0,
        "latencyMs": {"count": 2, "p50": 6, "p90": 8, "max": 10},
        "dynamicFilteredRate": {"mean": 0.2, "p90": 0.3},
        "densityMean": {"mean": 0.2, "p90": 0.3},
        "stability": {
            "iouPrevMean": 0.8,
            "iouPrevP90": 0.9,
            "flickerRatePrevMean": 0.1,
            "flickerRatePrevP90": 0.2,
            "hotspotCountMean": 5.0,
            "hotspotCountP90": 6.0,
        },
        "shiftUsedRate": shift_used_rate,
        "shiftGateRejectRate": shift_reject_rate,
        "shiftGateTopReasons": [{"reason": top_reason, "count": 2}],
    }
    payload["quality"] = quality
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_leaderboard_has_shift_gate_cols() -> None:
    with TestClient(app) as client:
        keep_id, keep_dir = _upload(client, "run_package_min", "shift_gate_keep_case")
        drop_id, drop_dir = _upload(client, "run_package_min", "shift_gate_drop_case")

        _set_costmap_fused_quality(
            keep_dir / "report.json",
            shift_used_rate=0.8,
            shift_reject_rate=0.1,
            top_reason="tracking_rate_low",
        )
        _set_costmap_fused_quality(
            drop_dir / "report.json",
            shift_used_rate=0.1,
            shift_reject_rate=0.9,
            top_reason="align_residual_high",
        )

        resp = client.get(
            "/api/run_packages",
            params={"sort": "costmap_fused_shift_gate_reject_rate", "order": "asc", "limit": 100},
        )
        assert resp.status_code == 200, resp.text
        items = resp.json().get("items", [])
        keep = next((row for row in items if row.get("runId") == keep_id), None)
        drop = next((row for row in items if row.get("runId") == drop_id), None)
        assert keep is not None
        assert drop is not None
        assert float(keep.get("costmap_fused_shift_gate_reject_rate", 0.0) or 0.0) == 0.1
        assert float(drop.get("costmap_fused_shift_gate_reject_rate", 0.0) or 0.0) == 0.9
        assert items.index(keep) < items.index(drop)

        filtered = client.get(
            "/api/run_packages",
            params={
                "max_costmap_fused_shift_gate_reject_rate": 0.2,
                "min_costmap_fused_shift_used_rate": 0.5,
                "limit": 100,
            },
        )
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(row.get("runId") == keep_id for row in filtered_items)
        assert not any(row.get("runId") == drop_id for row in filtered_items)

        page = client.get("/runs", params={"sort": "costmap_fused_shift_gate_reject_rate", "order": "asc"})
        assert page.status_code == 200, page.text
        assert "Costmap Fused ShiftReject Rate" in page.text
        assert "Costmap Fused ShiftReject TopReason" in page.text

        shutil.rmtree(keep_dir, ignore_errors=True)
        shutil.rmtree(drop_dir, ignore_errors=True)

