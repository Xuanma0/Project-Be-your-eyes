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


def _set_seg_prompt(report_path: Path, *, present: bool, text_chars: int) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        payload = {}
    payload["segPrompt"] = {
        "present": present,
        "events": 1 if present else 0,
        "targetsCountTotal": 1 if present else 0,
        "textCharsTotal": text_chars,
        "boxesTotal": 0,
        "pointsTotal": 0,
        "promptVersion": "v1" if present else None,
        "promptVersionDiversityCount": 1 if present else 0,
        "budget": {
            "textCharsTotal": text_chars,
            "boxesTotal": 0,
            "pointsTotal": 0,
        },
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_seg_prompt_cols() -> None:
    with TestClient(app) as client:
        low_run_id, low_dir = _upload(client, "run_package_min", "seg_prompt_low")
        high_run_id, high_dir = _upload(client, "run_package_min", "seg_prompt_high")

        _set_seg_prompt(low_dir / "report.json", present=True, text_chars=8)
        _set_seg_prompt(high_dir / "report.json", present=True, text_chars=64)

        rows_resp = client.get("/api/run_packages", params={"sort": "seg_prompt_text_chars_total", "order": "desc", "limit": 100})
        assert rows_resp.status_code == 200, rows_resp.text
        rows = rows_resp.json().get("items", [])
        high = next((item for item in rows if item.get("runId") == high_run_id), None)
        low = next((item for item in rows if item.get("runId") == low_run_id), None)
        assert high is not None
        assert low is not None
        assert bool(high.get("seg_prompt_present")) is True
        assert int(high.get("seg_prompt_text_chars_total", 0)) == 64
        assert rows.index(high) < rows.index(low)

        filtered_resp = client.get("/api/run_packages", params={"min_seg_prompt_text_chars": 32, "limit": 100})
        assert filtered_resp.status_code == 200, filtered_resp.text
        filtered = filtered_resp.json().get("items", [])
        assert any(item.get("runId") == high_run_id for item in filtered)
        assert not any(item.get("runId") == low_run_id for item in filtered)

        page_resp = client.get("/runs", params={"min_seg_prompt_text_chars": 1})
        assert page_resp.status_code == 200, page_resp.text
        assert "Seg Prompt" in page_resp.text
        assert "Seg Prompt Chars" in page_resp.text

        shutil.rmtree(low_dir, ignore_errors=True)
        shutil.rmtree(high_dir, ignore_errors=True)
