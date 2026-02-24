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
        files={"file": ("frame_user_e2e_cols.zip", payload, "application/zip")},
        data={"scenarioTag": tag},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return str(body["runId"]), Path(body["runDir"])


def _set_frame_user_e2e(report_path: Path, *, p90: int, max_value: int, coverage: float) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    payload["frameUserE2E"] = {
        "present": True,
        "events": 2,
        "coverage": {"framesWithInputDeclared": 2, "framesWithAck": 2, "ratio": float(coverage)},
        "totalMs": {
            "count": 2,
            "p50": int(p90 // 2),
            "p90": int(p90),
            "p99": int(max_value),
            "max": int(max_value),
            "valuesSample": [int(p90 // 2), int(p90)],
        },
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_frame_user_e2e_cols() -> None:
    with TestClient(app) as client:
        run_a, dir_a = _upload(client, "frame_user_e2e_low")
        run_b, dir_b = _upload(client, "frame_user_e2e_high")

        _set_frame_user_e2e(dir_a / "report.json", p90=140, max_value=180, coverage=1.0)
        _set_frame_user_e2e(dir_b / "report.json", p90=260, max_value=320, coverage=0.5)

        rows = client.get("/api/run_packages", params={"sort": "frame_user_e2e_p90", "order": "desc", "limit": 100})
        assert rows.status_code == 200, rows.text
        items = rows.json().get("items", [])
        high = next((item for item in items if item.get("runId") == run_b), None)
        low = next((item for item in items if item.get("runId") == run_a), None)
        assert isinstance(high, dict)
        assert isinstance(low, dict)
        for key in ("frame_user_e2e_p90", "frame_user_e2e_max", "ack_coverage"):
            assert key in high
        assert int(high.get("frame_user_e2e_p90", 0) or 0) > int(low.get("frame_user_e2e_p90", 0) or 0)

        filtered = client.get(
            "/api/run_packages",
            params={"max_frame_user_e2e_p90": 200, "max_frame_user_e2e_max": 200, "limit": 100},
        )
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(item.get("runId") == run_a for item in filtered_items)
        assert all(item.get("runId") != run_b for item in filtered_items)

        shutil.rmtree(dir_a, ignore_errors=True)
        shutil.rmtree(dir_b, ignore_errors=True)
