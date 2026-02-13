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


def _set_risk_latency(report_path: Path, *, p50: int, p90: int, p99: int, max_value: int) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        payload = {}
    quality = payload.get("quality")
    if not isinstance(quality, dict):
        quality = {}
    quality["riskLatencyMs"] = {
        "count": 2,
        "p50": p50,
        "p90": p90,
        "p99": p99,
        "max": max_value,
        "valuesSample": [p50, p90],
    }
    payload["quality"] = quality
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_runs_leaderboard_risk_latency_filters_and_sort() -> None:
    with TestClient(app) as client:
        slow_run_id, slow_dir = _upload(client, "run_package_min", "risk_latency_slow_case")
        fast_run_id, fast_dir = _upload(client, "run_package_min", "risk_latency_fast_case")

        _set_risk_latency(slow_dir / "report.json", p50=150, p90=240, p99=260, max_value=280)
        _set_risk_latency(fast_dir / "report.json", p50=70, p90=110, p99=130, max_value=140)

        sorted_resp = client.get("/api/run_packages", params={"sort": "risk_latency_p90", "order": "asc", "limit": 100})
        assert sorted_resp.status_code == 200, sorted_resp.text
        items = sorted_resp.json().get("items", [])
        slow_item = next((item for item in items if item.get("runId") == slow_run_id), None)
        fast_item = next((item for item in items if item.get("runId") == fast_run_id), None)
        assert slow_item is not None
        assert fast_item is not None
        assert int(fast_item.get("risk_latency_p90", 0)) == 110
        assert int(slow_item.get("risk_latency_p90", 0)) == 240
        assert items.index(fast_item) < items.index(slow_item)

        filtered_p90 = client.get("/api/run_packages", params={"max_risk_latency_p90": 150, "limit": 100})
        assert filtered_p90.status_code == 200, filtered_p90.text
        filtered_p90_items = filtered_p90.json().get("items", [])
        assert any(item.get("runId") == fast_run_id for item in filtered_p90_items)
        assert not any(item.get("runId") == slow_run_id for item in filtered_p90_items)

        filtered_max = client.get("/api/run_packages", params={"max_risk_latency_max": 200, "limit": 100})
        assert filtered_max.status_code == 200, filtered_max.text
        filtered_max_items = filtered_max.json().get("items", [])
        assert any(item.get("runId") == fast_run_id for item in filtered_max_items)
        assert not any(item.get("runId") == slow_run_id for item in filtered_max_items)

        page = client.get("/runs", params={"sort": "risk_latency_p90", "order": "asc"})
        assert page.status_code == 200, page.text
        assert "Risk p90(ms)" in page.text

        shutil.rmtree(slow_dir, ignore_errors=True)
        shutil.rmtree(fast_dir, ignore_errors=True)
