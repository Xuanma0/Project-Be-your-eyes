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


def _upload(client: TestClient, tag: str) -> tuple[str, Path]:
    payload = _zip_fixture_bytes("run_package_min")
    response = client.post(
        "/api/run_package/upload",
        files={"file": ("slam_ctx_cols.zip", payload, "application/zip")},
        data={"scenarioTag": tag},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return str(body["runId"]), Path(body["runDir"])


def _set_slam_context(report_path: Path, *, chars_p90: int, trunc_rate: float, tracking_rate_mean: float) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    payload["slamContext"] = {
        "present": True,
        "events": 1,
        "budgetDefault": {"maxChars": 512, "mode": "last_pose_and_health"},
        "out": {"charsTotalP90": chars_p90, "tokenApproxP90": max(0, chars_p90 // 4)},
        "truncation": {"posesDroppedTotal": 0, "charsDroppedTotal": 0, "truncationRate": trunc_rate},
        "health": {"trackingRateMean": tracking_rate_mean, "lostStreakMax": 1},
        "quality": {"ateRmseMMean": None, "ateRmseMP90": None},
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_slam_ctx_cols() -> None:
    with TestClient(app) as client:
        run_a, dir_a = _upload(client, "slam_ctx_low")
        run_b, dir_b = _upload(client, "slam_ctx_high")

        _set_slam_context(dir_a / "report.json", chars_p90=64, trunc_rate=0.30, tracking_rate_mean=0.40)
        _set_slam_context(dir_b / "report.json", chars_p90=220, trunc_rate=0.05, tracking_rate_mean=0.95)

        rows_resp = client.get("/api/run_packages", params={"sort": "slam_ctx_chars_p90", "order": "desc", "limit": 100})
        assert rows_resp.status_code == 200, rows_resp.text
        items = rows_resp.json().get("items", [])
        high = next((item for item in items if item.get("runId") == run_b), None)
        low = next((item for item in items if item.get("runId") == run_a), None)
        assert isinstance(high, dict)
        assert isinstance(low, dict)
        assert "slam_ctx_present" in high
        assert "slam_ctx_chars_p90" in high
        assert "slam_ctx_trunc_rate" in high
        assert "slam_tracking_rate_mean" in high
        assert int(high.get("slam_ctx_chars_p90", 0) or 0) > int(low.get("slam_ctx_chars_p90", 0) or 0)

        filtered = client.get(
            "/api/run_packages",
            params={
                "require_slam_ctx_present": "true",
                "max_slam_ctx_trunc_rate": 0.10,
                "min_slam_tracking_rate_mean": 0.80,
                "limit": 100,
            },
        )
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(item.get("runId") == run_b for item in filtered_items)
        assert all(item.get("runId") != run_a for item in filtered_items)

        shutil.rmtree(dir_a, ignore_errors=True)
        shutil.rmtree(dir_b, ignore_errors=True)
