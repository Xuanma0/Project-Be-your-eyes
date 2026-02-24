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
        files={"file": ("confirm_cols.zip", payload, "application/zip")},
        data={"scenarioTag": tag},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return str(body["runId"]), Path(body["runDir"])


def _set_confirm_metrics(report_path: Path, *, responses: int, latency_p90: int) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    payload["planAck"] = {
        "present": True,
        "framesWithPlan": 2,
        "framesWithAck": 2,
        "ackKindDiversity": 2,
        "ttsAckFrames": 1,
        "arAckFrames": 1,
        "ttsAckRate": 0.5,
        "arAckRate": 0.5,
        "confirmResponsesFromUnity": int(responses),
        "confirmResponseLatencyMs": {
            "count": int(max(1, responses)),
            "p50": int(latency_p90),
            "p90": int(latency_p90),
            "p99": int(latency_p90),
            "max": int(latency_p90),
        },
        "byKindCounts": {"tts": 1, "ar": 1},
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_confirm_response_cols() -> None:
    with TestClient(app) as client:
        run_a, dir_a = _upload(client, "confirm_cols_a")
        run_b, dir_b = _upload(client, "confirm_cols_b")

        _set_confirm_metrics(dir_a / "report.json", responses=1, latency_p90=180)
        _set_confirm_metrics(dir_b / "report.json", responses=3, latency_p90=420)

        rows_response = client.get("/api/run_packages", params={"limit": 100})
        assert rows_response.status_code == 200, rows_response.text
        items = rows_response.json().get("items", [])
        row_a = next((item for item in items if item.get("runId") == run_a), None)
        row_b = next((item for item in items if item.get("runId") == run_b), None)
        assert isinstance(row_a, dict)
        assert isinstance(row_b, dict)
        for key in ("confirm_responses", "confirm_response_p90"):
            assert key in row_a
            assert key in row_b
        assert int(row_a.get("confirm_responses", 0) or 0) != int(row_b.get("confirm_responses", 0) or 0)

        shutil.rmtree(dir_a, ignore_errors=True)
        shutil.rmtree(dir_b, ignore_errors=True)
