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


def _set_seg_quality(report_path: Path, *, f1: float, coverage: float, p90: int) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        payload = {}
    quality = payload.get("quality")
    if not isinstance(quality, dict):
        quality = {}
    quality["seg"] = {
        "present": True,
        "framesTotal": 2,
        "framesWithGt": 2,
        "framesWithPred": 2,
        "coverage": coverage,
        "precision": f1,
        "recall": f1,
        "f1At50": f1,
        "meanIoU": f1,
        "latencyMs": {"count": 2, "p50": max(1, p90 // 2), "p90": p90, "max": p90 + 10},
        "topMisses": [],
        "topFP": [],
    }
    payload["quality"] = quality
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_seg_cols() -> None:
    with TestClient(app) as client:
        fast_run_id, fast_dir = _upload(client, "run_package_min", "seg_fast_case")
        slow_run_id, slow_dir = _upload(client, "run_package_min", "seg_slow_case")

        _set_seg_quality(fast_dir / "report.json", f1=0.90, coverage=1.00, p90=40)
        _set_seg_quality(slow_dir / "report.json", f1=0.30, coverage=0.50, p90=120)

        resp = client.get("/api/run_packages", params={"sort": "seg_f1_50", "order": "desc", "limit": 100})
        assert resp.status_code == 200, resp.text
        items = resp.json().get("items", [])
        fast = next((item for item in items if item.get("runId") == fast_run_id), None)
        slow = next((item for item in items if item.get("runId") == slow_run_id), None)
        assert fast is not None
        assert slow is not None
        assert float(fast.get("seg_f1_50", 0.0)) == 0.9
        assert float(slow.get("seg_f1_50", 0.0)) == 0.3
        assert items.index(fast) < items.index(slow)

        filtered = client.get(
            "/api/run_packages",
            params={"min_seg_f1_50": 0.8, "min_seg_coverage": 0.8, "max_seg_latency_p90": 60, "limit": 100},
        )
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(item.get("runId") == fast_run_id for item in filtered_items)
        assert not any(item.get("runId") == slow_run_id for item in filtered_items)

        page = client.get("/runs", params={"sort": "seg_f1_50", "order": "desc"})
        assert page.status_code == 200, page.text
        assert "Seg F1@0.5" in page.text
        assert "Seg Coverage" in page.text
        assert "Seg p90(ms)" in page.text

        shutil.rmtree(fast_dir, ignore_errors=True)
        shutil.rmtree(slow_dir, ignore_errors=True)
