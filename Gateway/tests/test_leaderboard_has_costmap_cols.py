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


def _set_costmap_quality(report_path: Path, *, coverage: float, latency_p90: int, density_mean: float, dynamic_mean: float) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        payload = {}
    quality = payload.get("quality")
    if not isinstance(quality, dict):
        quality = {}
    quality["costmap"] = {
        "present": True,
        "framesTotal": 2,
        "framesWithCostmap": 2,
        "coverage": coverage,
        "latencyMs": {"count": 2, "p50": max(1, latency_p90 // 2), "p90": latency_p90, "max": latency_p90 + 5},
        "dynamicFilteredRate": {"mean": dynamic_mean, "p90": dynamic_mean},
        "densityMean": {"mean": density_mean, "p90": density_mean},
    }
    payload["quality"] = quality
    plan_context = payload.get("planContext")
    if not isinstance(plan_context, dict):
        plan_context = {}
    plan_context["present"] = True
    plan_context["costmap"] = {
        "hitRate": 1.0,
        "coverageMean": 1.0,
        "coverageP90": 1.0,
        "contextUsedRate": 1.0,
    }
    payload["planContext"] = plan_context
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def test_leaderboard_has_costmap_cols() -> None:
    with TestClient(app) as client:
        fast_id, fast_dir = _upload(client, "run_package_min", "costmap_fast_case")
        slow_id, slow_dir = _upload(client, "run_package_min", "costmap_slow_case")

        _set_costmap_quality(fast_dir / "report.json", coverage=1.0, latency_p90=30, density_mean=0.10, dynamic_mean=0.05)
        _set_costmap_quality(slow_dir / "report.json", coverage=0.4, latency_p90=140, density_mean=0.40, dynamic_mean=0.30)

        resp = client.get("/api/run_packages", params={"sort": "costmap_latency_p90", "order": "asc", "limit": 100})
        assert resp.status_code == 200, resp.text
        items = resp.json().get("items", [])
        fast = next((row for row in items if row.get("runId") == fast_id), None)
        slow = next((row for row in items if row.get("runId") == slow_id), None)
        assert fast is not None
        assert slow is not None
        assert int(fast.get("costmap_latency_p90", 0) or 0) == 30
        assert int(slow.get("costmap_latency_p90", 0) or 0) == 140
        assert items.index(fast) < items.index(slow)

        filtered = client.get(
            "/api/run_packages",
            params={
                "min_costmap_coverage": 0.8,
                "max_costmap_latency_p90": 60,
                "max_costmap_dynamic_filter_rate_mean": 0.1,
                "require_plan_costmap_ctx_used": "true",
                "limit": 100,
            },
        )
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(row.get("runId") == fast_id for row in filtered_items)
        assert not any(row.get("runId") == slow_id for row in filtered_items)

        page = client.get("/runs", params={"sort": "costmap_latency_p90", "order": "asc"})
        assert page.status_code == 200, page.text
        assert "Costmap Coverage" in page.text
        assert "Costmap p90(ms)" in page.text

        shutil.rmtree(fast_dir, ignore_errors=True)
        shutil.rmtree(slow_dir, ignore_errors=True)
