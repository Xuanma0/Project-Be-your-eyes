from __future__ import annotations

import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


def _zip_dir(path: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in path.rglob("*"):
            if item.is_file():
                zf.write(item, item.relative_to(path))
    return buffer.getvalue()


def _rewrite_events(events_path: Path, *, plan_latency: int, with_response: bool) -> None:
    rows = []
    for raw in events_path.read_text(encoding="utf-8-sig").splitlines():
        if not raw.strip():
            continue
        row = json.loads(raw)
        if str(row.get("name", "")).strip().lower() == "plan.generate":
            row["latencyMs"] = int(plan_latency)
        rows.append(row)

    rows.append(
        {
            "schemaVersion": "byes.event.v1",
            "tsMs": 1709000000300,
            "runId": rows[0].get("runId", "fixture"),
            "frameSeq": 1,
            "component": "gateway",
            "category": "ui",
            "name": "ui.confirm_request",
            "phase": "start",
            "status": "ok",
            "latencyMs": None,
            "payload": {"confirmId": "confirm-plan", "text": "stop?", "timeoutMs": 3000},
        }
    )
    if with_response:
        rows.append(
            {
                "schemaVersion": "byes.event.v1",
                "tsMs": 1709000000400,
                "runId": rows[0].get("runId", "fixture"),
                "frameSeq": 1,
                "component": "gateway",
                "category": "ui",
                "name": "ui.confirm_response",
                "phase": "result",
                "status": "ok",
                "latencyMs": 100,
                "payload": {"confirmId": "confirm-plan", "accepted": True, "latencyMs": 100},
            }
        )

    events_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _upload_package(client: TestClient, package_dir: Path, scenario: str) -> tuple[str, Path]:
    payload = _zip_dir(package_dir)
    response = client.post(
        "/api/run_package/upload",
        files={"file": (f"{package_dir.name}.zip", payload, "application/zip")},
        data={"scenarioTag": scenario},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return str(body["runId"]), Path(body["runDir"])


def test_runs_filter_sort_plan_eval() -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "run_package_with_plan_llm_stub_min"
    work = Path(tempfile.mkdtemp(prefix="plan_eval_runs_"))
    slow_pkg = work / "slow"
    fast_pkg = work / "fast"
    shutil.copytree(fixture, slow_pkg)
    shutil.copytree(fixture, fast_pkg)

    _rewrite_events(slow_pkg / "events" / "events_v1.jsonl", plan_latency=300, with_response=False)
    _rewrite_events(fast_pkg / "events" / "events_v1.jsonl", plan_latency=60, with_response=True)

    with TestClient(app) as client:
        slow_run_id, slow_run_dir = _upload_package(client, slow_pkg, "plan_eval_slow")
        fast_run_id, fast_run_dir = _upload_package(client, fast_pkg, "plan_eval_fast")

        sorted_resp = client.get(
            "/api/run_packages",
            params={"sort": "plan_latency_p90", "order": "asc", "limit": 200},
        )
        assert sorted_resp.status_code == 200, sorted_resp.text
        items = sorted_resp.json().get("items", [])
        subset = [row for row in items if row.get("runId") in {slow_run_id, fast_run_id}]
        assert len(subset) == 2
        assert subset[0].get("runId") == fast_run_id
        assert "plan_latency_p90" in subset[0]
        assert "confirm_requests" in subset[0]

        filtered = client.get(
            "/api/run_packages",
            params={"max_confirm_timeouts": 0, "limit": 200},
        )
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(row.get("runId") == fast_run_id for row in filtered_items)
        assert not any(row.get("runId") == slow_run_id for row in filtered_items)

        shutil.rmtree(slow_run_dir, ignore_errors=True)
        shutil.rmtree(fast_run_dir, ignore_errors=True)

    shutil.rmtree(work, ignore_errors=True)
