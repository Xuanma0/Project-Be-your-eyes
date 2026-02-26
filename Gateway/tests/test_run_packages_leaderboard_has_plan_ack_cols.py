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
        files={"file": ("plan_ack_cols.zip", payload, "application/zip")},
        data={"scenarioTag": tag},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return str(body["runId"]), Path(body["runDir"])


def _set_plan_ack_metrics(report_path: Path, *, tts_rate: float, ar_rate: float) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    payload["planAck"] = {
        "present": True,
        "framesWithPlan": 4,
        "framesWithAck": 3,
        "ackKindDiversity": 2,
        "ttsAckFrames": 2,
        "arAckFrames": 1,
        "ttsAckRate": float(tts_rate),
        "arAckRate": float(ar_rate),
        "byKindCounts": {"tts": 2, "ar": 1},
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_plan_ack_cols() -> None:
    with TestClient(app) as client:
        run_a, dir_a = _upload(client, "plan_ack_cols_a")
        run_b, dir_b = _upload(client, "plan_ack_cols_b")

        _set_plan_ack_metrics(dir_a / "report.json", tts_rate=0.25, ar_rate=0.5)
        _set_plan_ack_metrics(dir_b / "report.json", tts_rate=0.75, ar_rate=0.25)

        rows_response = client.get("/api/run_packages", params={"limit": 100})
        assert rows_response.status_code == 200, rows_response.text
        items = rows_response.json().get("items", [])
        row_a = next((item for item in items if item.get("runId") == run_a), None)
        row_b = next((item for item in items if item.get("runId") == run_b), None)
        assert isinstance(row_a, dict)
        assert isinstance(row_b, dict)
        for key in ("tts_ack_rate", "ar_ack_rate"):
            assert key in row_a
            assert key in row_b
        assert float(row_a.get("tts_ack_rate", 0.0) or 0.0) != float(row_b.get("tts_ack_rate", 0.0) or 0.0)

        shutil.rmtree(dir_a, ignore_errors=True)
        shutil.rmtree(dir_b, ignore_errors=True)
