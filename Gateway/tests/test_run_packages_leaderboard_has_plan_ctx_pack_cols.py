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
        files={"file": ("plan_ctx_pack_cols.zip", payload, "application/zip")},
        data={"scenarioTag": tag},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return str(body["runId"]), Path(body["runDir"])


def _set_plan_context_pack(report_path: Path, *, chars_p90: int, trunc_rate: float) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    payload["planContextPack"] = {
        "present": True,
        "events": 1,
        "budgetDefault": {"maxChars": 256, "mode": "seg_plus_pov_plus_risk"},
        "out": {
            "charsTotalP90": chars_p90,
            "segCharsP90": int(chars_p90 * 0.25),
            "povCharsP90": int(chars_p90 * 0.35),
            "riskCharsP90": int(chars_p90 * 0.4),
        },
        "truncation": {"charsDroppedTotal": int(trunc_rate * 100.0), "truncationRate": trunc_rate},
        "modeDiversityCount": 1,
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_plan_ctx_pack_cols() -> None:
    with TestClient(app) as client:
        run_a, dir_a = _upload(client, "plan_ctx_pack_low")
        run_b, dir_b = _upload(client, "plan_ctx_pack_high")

        _set_plan_context_pack(dir_a / "report.json", chars_p90=120, trunc_rate=0.40)
        _set_plan_context_pack(dir_b / "report.json", chars_p90=280, trunc_rate=0.05)

        rows = client.get("/api/run_packages", params={"sort": "plan_ctx_chars_p90", "order": "desc", "limit": 100})
        assert rows.status_code == 200, rows.text
        items = rows.json().get("items", [])
        high = next((item for item in items if item.get("runId") == run_b), None)
        low = next((item for item in items if item.get("runId") == run_a), None)
        assert isinstance(high, dict)
        assert isinstance(low, dict)
        assert "plan_ctx_chars_p90" in high
        assert "plan_ctx_trunc_rate" in high
        assert "plan_ctx_seg_chars_p90" in high
        assert "plan_ctx_pov_chars_p90" in high
        assert "plan_ctx_risk_chars_p90" in high
        assert int(high.get("plan_ctx_chars_p90", 0) or 0) > int(low.get("plan_ctx_chars_p90", 0) or 0)

        filtered = client.get(
            "/api/run_packages",
            params={"max_plan_ctx_trunc_rate": 0.1, "min_plan_ctx_chars_p90": 200, "limit": 100},
        )
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(item.get("runId") == run_b for item in filtered_items)
        assert all(item.get("runId") != run_a for item in filtered_items)

        shutil.rmtree(dir_a, ignore_errors=True)
        shutil.rmtree(dir_b, ignore_errors=True)
