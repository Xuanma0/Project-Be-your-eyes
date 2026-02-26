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
        files={"file": ("mode_cols.zip", payload, "application/zip")},
        data={"scenarioTag": tag},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return str(body["runId"]), Path(body["runDir"])


def _set_mode_metrics(report_path: Path, *, switches: int, diversity: int, last_mode: str, coverage: float) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    payload["mode"] = {
        "present": True,
        "events": int(max(0, switches)),
        "switches": int(max(0, switches)),
        "modeDiversity": int(max(0, diversity)),
        "lastMode": str(last_mode),
        "framesWithModeMeta": 2,
        "modeMetaCoverage": float(max(0.0, min(1.0, coverage))),
        "byModeCounts": {"walk": 1, "read_text": 1, "inspect": 0},
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_mode_cols() -> None:
    with TestClient(app) as client:
        run_a, dir_a = _upload(client, "mode_cols_a")
        run_b, dir_b = _upload(client, "mode_cols_b")

        _set_mode_metrics(dir_a / "report.json", switches=2, diversity=2, last_mode="read_text", coverage=1.0)
        _set_mode_metrics(dir_b / "report.json", switches=1, diversity=1, last_mode="walk", coverage=0.5)

        rows_response = client.get("/api/run_packages", params={"limit": 100})
        assert rows_response.status_code == 200, rows_response.text
        items = rows_response.json().get("items", [])
        row_a = next((item for item in items if item.get("runId") == run_a), None)
        row_b = next((item for item in items if item.get("runId") == run_b), None)
        assert isinstance(row_a, dict)
        assert isinstance(row_b, dict)
        for key in ("mode_switches", "mode_diversity", "mode_last", "mode_meta_coverage"):
            assert key in row_a
            assert key in row_b
        assert str(row_a.get("mode_last", "")) != str(row_b.get("mode_last", ""))

        shutil.rmtree(dir_a, ignore_errors=True)
        shutil.rmtree(dir_b, ignore_errors=True)

