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


def _set_depth_quality(report_path: Path, *, absrel: float, rmse: float, delta1: float, coverage: float, p90: int) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        payload = {}
    quality = payload.get("quality")
    if not isinstance(quality, dict):
        quality = {}
    quality["depth"] = {
        "present": True,
        "framesTotal": 2,
        "framesWithGt": 2,
        "framesWithPred": 2,
        "coverage": coverage,
        "absRel": absrel,
        "rmse": rmse,
        "delta1": delta1,
        "validFrames": 2,
        "latencyMs": {"count": 2, "p50": max(1, p90 // 2), "p90": p90, "max": p90 + 10},
        "topBadCells": [],
    }
    payload["quality"] = quality
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_depth_cols() -> None:
    with TestClient(app) as client:
        better_run_id, better_dir = _upload(client, "run_package_min", "depth_better_case")
        worse_run_id, worse_dir = _upload(client, "run_package_min", "depth_worse_case")

        _set_depth_quality(better_dir / "report.json", absrel=0.05, rmse=12.0, delta1=0.95, coverage=1.0, p90=45)
        _set_depth_quality(worse_dir / "report.json", absrel=0.20, rmse=40.0, delta1=0.70, coverage=0.6, p90=120)

        resp = client.get("/api/run_packages", params={"sort": "depth_delta1", "order": "desc", "limit": 100})
        assert resp.status_code == 200, resp.text
        items = resp.json().get("items", [])
        better = next((item for item in items if item.get("runId") == better_run_id), None)
        worse = next((item for item in items if item.get("runId") == worse_run_id), None)
        assert better is not None
        assert worse is not None
        assert float(better.get("depth_delta1", 0.0)) == 0.95
        assert float(worse.get("depth_delta1", 0.0)) == 0.7
        assert items.index(better) < items.index(worse)

        filtered = client.get(
            "/api/run_packages",
            params={"min_depth_delta1": 0.9, "max_depth_absrel": 0.1, "min_depth_coverage": 0.9, "max_depth_latency_p90": 60, "limit": 100},
        )
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(item.get("runId") == better_run_id for item in filtered_items)
        assert not any(item.get("runId") == worse_run_id for item in filtered_items)

        page = client.get("/runs", params={"sort": "depth_delta1", "order": "desc"})
        assert page.status_code == 200, page.text
        assert "Depth Delta1" in page.text
        assert "Depth AbsRel" in page.text
        assert "Depth p90(ms)" in page.text

        shutil.rmtree(better_dir, ignore_errors=True)
        shutil.rmtree(worse_dir, ignore_errors=True)

