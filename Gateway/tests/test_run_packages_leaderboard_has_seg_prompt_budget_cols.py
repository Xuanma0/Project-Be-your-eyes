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


def _set_seg_prompt(report_path: Path, *, text_chars: int, chars_out: int, targets_out: int, dropped: int, trunc_rate: float) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        payload = {}
    payload["segPrompt"] = {
        "present": True,
        "events": 1,
        "targetsCountTotal": targets_out,
        "textCharsTotal": text_chars,
        "boxesTotal": 1,
        "pointsTotal": 2,
        "promptVersion": "v1",
        "promptVersionDiversityCount": 1,
        "budget": {"maxChars": 256, "maxTargets": 8, "maxBoxes": 4, "maxPoints": 8, "mode": "targets_text_boxes_points"},
        "out": {"targetsCountTotal": targets_out, "textCharsTotal": min(text_chars, chars_out), "boxesTotal": 1, "pointsTotal": 2, "charsTotal": chars_out},
        "truncation": {"targetsDropped": dropped, "boxesDropped": 0, "pointsDropped": 0, "textCharsDropped": max(0, text_chars - chars_out)},
        "truncationRate": trunc_rate,
        "packed": {"trueCount": 1, "falseCount": 0},
        "warningsCount": 1 if dropped > 0 else 0,
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_seg_prompt_budget_cols() -> None:
    with TestClient(app) as client:
        low_run_id, low_dir = _upload(client, "run_package_min", "seg_prompt_budget_low")
        high_run_id, high_dir = _upload(client, "run_package_min", "seg_prompt_budget_high")

        _set_seg_prompt(low_dir / "report.json", text_chars=32, chars_out=32, targets_out=2, dropped=0, trunc_rate=0.0)
        _set_seg_prompt(high_dir / "report.json", text_chars=300, chars_out=120, targets_out=6, dropped=5, trunc_rate=0.45)

        rows_resp = client.get("/api/run_packages", params={"sort": "seg_prompt_trunc_rate", "order": "desc", "limit": 100})
        assert rows_resp.status_code == 200, rows_resp.text
        rows = rows_resp.json().get("items", [])
        high = next((item for item in rows if item.get("runId") == high_run_id), None)
        low = next((item for item in rows if item.get("runId") == low_run_id), None)
        assert high is not None and low is not None
        assert float(high.get("seg_prompt_trunc_rate", 0.0) or 0.0) > float(low.get("seg_prompt_trunc_rate", 0.0) or 0.0)
        assert rows.index(high) < rows.index(low)
        assert int(high.get("seg_prompt_chars_out", 0) or 0) == 120
        assert int(high.get("seg_prompt_targets_out", 0) or 0) == 6

        filtered_resp = client.get(
            "/api/run_packages",
            params={"max_seg_prompt_trunc_rate": 0.1, "max_seg_prompt_trunc_dropped": 1, "limit": 100},
        )
        assert filtered_resp.status_code == 200, filtered_resp.text
        filtered = filtered_resp.json().get("items", [])
        assert any(item.get("runId") == low_run_id for item in filtered)
        assert not any(item.get("runId") == high_run_id for item in filtered)

        shutil.rmtree(low_dir, ignore_errors=True)
        shutil.rmtree(high_dir, ignore_errors=True)
