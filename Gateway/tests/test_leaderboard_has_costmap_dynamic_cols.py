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


def test_leaderboard_has_costmap_dynamic_cols() -> None:
    with TestClient(app) as client:
        payload = _zip_fixture_bytes("run_package_with_costmap_dynamic_track_min")
        response = client.post(
            "/api/run_package/upload",
            files={"file": ("run_package_with_costmap_dynamic_track_min.zip", payload, "application/zip")},
            data={"scenarioTag": "costmap_dynamic_cols_case"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        run_id = str(body["runId"])
        run_dir = Path(body["runDir"])

        listing = client.get(
            "/api/run_packages",
            params={
                "sort": "costmap_dynamic_mask_used_rate",
                "order": "desc",
                "min_costmap_dynamic_temporal_used_rate": 0.1,
                "min_costmap_dynamic_mask_used_rate": 0.1,
                "max_costmap_dynamic_tracks_used_mean": 10.0,
                "limit": 50,
            },
        )
        assert listing.status_code == 200, listing.text
        items = listing.json().get("items", [])
        row = next((item for item in items if str(item.get("runId")) == run_id), None)
        assert isinstance(row, dict)
        assert "costmap_dynamic_temporal_used_rate" in row
        assert "costmap_dynamic_tracks_used_mean" in row
        assert "costmap_dynamic_mask_used_rate" in row
        assert float(row.get("costmap_dynamic_temporal_used_rate", 0.0) or 0.0) > 0.0
        assert float(row.get("costmap_dynamic_mask_used_rate", 0.0) or 0.0) > 0.0

        page = client.get("/runs", params={"sort": "costmap_dynamic_mask_used_rate", "order": "desc"})
        assert page.status_code == 200, page.text
        assert "costmap_dynamic_mask_used_rate" in page.text

        shutil.rmtree(run_dir, ignore_errors=True)
