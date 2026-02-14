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


def _set_seg_mask_quality(report_path: Path, *, mask_f1: float, mask_cov: float, mask_iou: float) -> None:
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
        "coverage": 1.0,
        "precision": 1.0,
        "recall": 1.0,
        "f1At50": 1.0,
        "meanIoU": 1.0,
        "latencyMs": {"count": 2, "p50": 20, "p90": 30, "max": 30},
        "maskMeanIoU": mask_iou,
        "maskPrecision50": mask_f1,
        "maskRecall50": mask_f1,
        "maskF1_50": mask_f1,
        "maskFramesWithGt": 2,
        "maskFramesWithPred": 2,
        "maskCoverage": mask_cov,
        "maskTopMisses": [],
        "maskTopFP": [],
        "topMisses": [],
        "topFP": [],
    }
    payload["quality"] = quality
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_seg_mask_cols() -> None:
    with TestClient(app) as client:
        high_run_id, high_dir = _upload(client, "run_package_min", "seg_mask_high_case")
        low_run_id, low_dir = _upload(client, "run_package_min", "seg_mask_low_case")

        _set_seg_mask_quality(high_dir / "report.json", mask_f1=0.9, mask_cov=1.0, mask_iou=0.8)
        _set_seg_mask_quality(low_dir / "report.json", mask_f1=0.2, mask_cov=0.4, mask_iou=0.1)

        resp = client.get("/api/run_packages", params={"sort": "seg_mask_f1_50", "order": "desc", "limit": 100})
        assert resp.status_code == 200, resp.text
        items = resp.json().get("items", [])
        high = next((item for item in items if item.get("runId") == high_run_id), None)
        low = next((item for item in items if item.get("runId") == low_run_id), None)
        assert high is not None
        assert low is not None
        assert float(high.get("seg_mask_f1_50", 0.0)) == 0.9
        assert float(low.get("seg_mask_f1_50", 0.0)) == 0.2
        assert items.index(high) < items.index(low)

        filtered = client.get(
            "/api/run_packages",
            params={"min_seg_mask_f1_50": 0.8, "min_seg_mask_coverage": 0.8, "limit": 100},
        )
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(item.get("runId") == high_run_id for item in filtered_items)
        assert not any(item.get("runId") == low_run_id for item in filtered_items)

        page = client.get("/runs", params={"sort": "seg_mask_f1_50", "order": "desc"})
        assert page.status_code == 200, page.text
        assert "Seg Mask F1@0.5" in page.text
        assert "Seg Mask Coverage" in page.text
        assert "Seg Mask mIoU" in page.text

        shutil.rmtree(high_dir, ignore_errors=True)
        shutil.rmtree(low_dir, ignore_errors=True)
