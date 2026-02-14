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


def _set_seg_context(report_path: Path, *, chars_total: int, segments: int, dropped: int) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        payload = {}
    payload["segContext"] = {
        "present": True,
        "budget": {"maxChars": 512, "maxSegments": 16, "mode": "topk_by_score"},
        "stats": {
            "out": {
                "segments": int(segments),
                "uniqueLabels": int(max(1, segments)),
                "charsTotal": int(chars_total),
                "tokenApprox": int((chars_total + 3) // 4),
            },
            "truncation": {
                "segmentsDropped": int(dropped),
                "labelsDropped": int(min(dropped, 3)),
                "charsDropped": int(max(0, dropped * 8)),
            },
        },
        "text": {
            "summary": "seg context test",
            "promptFragmentLength": int(chars_total),
            "promptFragment": "x" * int(max(1, min(chars_total, 120))),
        },
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_seg_ctx_cols() -> None:
    with TestClient(app) as client:
        low_run_id, low_dir = _upload(client, "run_package_min", "seg_ctx_low")
        high_run_id, high_dir = _upload(client, "run_package_min", "seg_ctx_high")

        _set_seg_context(low_dir / "report.json", chars_total=64, segments=2, dropped=0)
        _set_seg_context(high_dir / "report.json", chars_total=240, segments=8, dropped=5)

        rows_resp = client.get("/api/run_packages", params={"sort": "seg_ctx_trunc_dropped", "order": "desc", "limit": 100})
        assert rows_resp.status_code == 200, rows_resp.text
        rows = rows_resp.json().get("items", [])
        high = next((item for item in rows if item.get("runId") == high_run_id), None)
        low = next((item for item in rows if item.get("runId") == low_run_id), None)
        assert high is not None and low is not None
        assert int(high.get("seg_ctx_trunc_dropped", 0) or 0) > int(low.get("seg_ctx_trunc_dropped", 0) or 0)
        assert rows.index(high) < rows.index(low)
        assert int(high.get("seg_ctx_chars", 0) or 0) == 240
        assert int(high.get("seg_ctx_segments", 0) or 0) == 8

        filtered_resp = client.get(
            "/api/run_packages",
            params={"max_seg_ctx_trunc_dropped": 0, "max_seg_ctx_chars": 100, "limit": 100},
        )
        assert filtered_resp.status_code == 200, filtered_resp.text
        filtered = filtered_resp.json().get("items", [])
        assert any(item.get("runId") == low_run_id for item in filtered)
        assert not any(item.get("runId") == high_run_id for item in filtered)

        shutil.rmtree(low_dir, ignore_errors=True)
        shutil.rmtree(high_dir, ignore_errors=True)
