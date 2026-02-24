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


def _set_plan_request(report_path: Path, *, seg_p90: int, seg_drop: int, pov_p90: int, fallback_used: bool) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        payload = {}
    payload["planRequest"] = {
        "present": True,
        "events": 1,
        "segIncludedCount": 1,
        "povIncludedCount": 1,
        "segCharsTotal": int(seg_p90),
        "segCharsP90": int(seg_p90),
        "segTruncSegmentsDroppedTotal": int(seg_drop),
        "povCharsTotal": int(pov_p90),
        "povCharsP90": int(pov_p90),
        "fallbackUsedCount": 1 if fallback_used else 0,
    }
    payload["planEval"] = {
        "present": True,
        "ruleAppliedCount": 1,
        "ruleHazardHintTop": "stairs_or_dropoff",
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_plan_request_cols() -> None:
    with TestClient(app) as client:
        run_a, dir_a = _upload(client, "run_package_min", "plan_req_low")
        run_b, dir_b = _upload(client, "run_package_min", "plan_req_high")

        _set_plan_request(dir_a / "report.json", seg_p90=64, seg_drop=0, pov_p90=100, fallback_used=False)
        _set_plan_request(dir_b / "report.json", seg_p90=240, seg_drop=3, pov_p90=280, fallback_used=True)

        response = client.get(
            "/api/run_packages",
            params={"sort": "plan_req_seg_trunc_dropped", "order": "desc", "limit": 100},
        )
        assert response.status_code == 200, response.text
        rows = response.json().get("items", [])
        high = next((item for item in rows if item.get("runId") == run_b), None)
        low = next((item for item in rows if item.get("runId") == run_a), None)
        assert high is not None and low is not None
        assert int(high.get("plan_req_seg_trunc_dropped", 0) or 0) > int(low.get("plan_req_seg_trunc_dropped", 0) or 0)
        assert "plan_req_seg_chars_p90" in high
        assert "plan_req_pov_chars_p90" in high
        assert "plan_req_fallback_used" in high
        assert "plan_rule_applied" in high

        filtered = client.get(
            "/api/run_packages",
            params={"max_plan_req_seg_chars_p90": 100, "plan_req_fallback_used": "false", "limit": 100},
        )
        assert filtered.status_code == 200, filtered.text
        items = filtered.json().get("items", [])
        assert any(item.get("runId") == run_a for item in items)
        assert not any(item.get("runId") == run_b for item in items)

        shutil.rmtree(dir_a, ignore_errors=True)
        shutil.rmtree(dir_b, ignore_errors=True)
