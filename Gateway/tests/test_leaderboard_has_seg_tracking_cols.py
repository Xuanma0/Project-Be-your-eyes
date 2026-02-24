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


def _set_seg_tracking_quality(report_path: Path, *, coverage: float, tracks_total: int, id_switches: int) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        payload = {}
    quality = payload.get("quality")
    if not isinstance(quality, dict):
        quality = {}
    quality["segTracking"] = {
        "present": True,
        "framesTotal": 2,
        "framesWithSeg": 2,
        "framesWithTrackId": 2,
        "trackCoverage": coverage,
        "tracksTotal": tracks_total,
        "avgTrackLen": 2.0,
        "trackLenP90": 2.0,
        "idSwitchCount": id_switches,
    }
    payload["quality"] = quality
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def test_leaderboard_has_seg_tracking_cols() -> None:
    with TestClient(app) as client:
        high_id, high_dir = _upload(client, "run_package_min", "seg_tracking_high_case")
        low_id, low_dir = _upload(client, "run_package_min", "seg_tracking_low_case")

        _set_seg_tracking_quality(high_dir / "report.json", coverage=1.0, tracks_total=2, id_switches=0)
        _set_seg_tracking_quality(low_dir / "report.json", coverage=0.5, tracks_total=1, id_switches=3)

        resp = client.get("/api/run_packages", params={"sort": "seg_track_coverage", "order": "desc", "limit": 100})
        assert resp.status_code == 200, resp.text
        items = resp.json().get("items", [])
        high = next((row for row in items if row.get("runId") == high_id), None)
        low = next((row for row in items if row.get("runId") == low_id), None)
        assert high is not None
        assert low is not None
        assert float(high.get("seg_track_coverage", 0.0) or 0.0) == 1.0
        assert int(high.get("seg_tracks_total", 0) or 0) == 2
        assert int(high.get("seg_id_switches", 0) or 0) == 0
        assert items.index(high) < items.index(low)

        filtered = client.get(
            "/api/run_packages",
            params={
                "min_seg_track_coverage": 0.8,
                "min_seg_tracks_total": 2,
                "max_seg_id_switches": 0,
                "limit": 100,
            },
        )
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(row.get("runId") == high_id for row in filtered_items)
        assert not any(row.get("runId") == low_id for row in filtered_items)

        page = client.get("/runs", params={"sort": "seg_track_coverage", "order": "desc"})
        assert page.status_code == 200, page.text
        assert "Seg Track Coverage" in page.text
        assert "Seg Tracks Total" in page.text
        assert "Seg ID Switches" in page.text

        shutil.rmtree(high_dir, ignore_errors=True)
        shutil.rmtree(low_dir, ignore_errors=True)
