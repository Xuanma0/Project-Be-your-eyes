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
        files={"file": ("plan_ctx_cols.zip", payload, "application/zip")},
        data={"scenarioTag": tag},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return str(body["runId"]), Path(body["runDir"])


def _set_plan_context(report_path: Path, *, used_rate: float, seg_cov: float, pov_cov: float) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    payload["planContext"] = {
        "present": True,
        "events": 1,
        "contextUsedRate": used_rate,
        "seg": {"hitRate": used_rate, "coverageMean": seg_cov, "coverageP90": seg_cov},
        "pov": {"hitRate": used_rate, "coverageMean": pov_cov, "coverageP90": pov_cov},
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_plan_ctx_cols() -> None:
    with TestClient(app) as client:
        run_a, dir_a = _upload(client, "plan_ctx_low")
        run_b, dir_b = _upload(client, "plan_ctx_high")

        _set_plan_context(dir_a / "report.json", used_rate=0.0, seg_cov=0.1, pov_cov=0.2)
        _set_plan_context(dir_b / "report.json", used_rate=1.0, seg_cov=0.9, pov_cov=0.8)

        rows = client.get("/api/run_packages", params={"sort": "plan_seg_ctx_coverage", "order": "desc", "limit": 100})
        assert rows.status_code == 200, rows.text
        items = rows.json().get("items", [])
        high = next((item for item in items if item.get("runId") == run_b), None)
        low = next((item for item in items if item.get("runId") == run_a), None)
        assert isinstance(high, dict)
        assert isinstance(low, dict)
        assert "plan_ctx_used" in high
        assert "plan_seg_ctx_coverage" in high
        assert "plan_pov_ctx_coverage" in high
        assert float(high.get("plan_seg_ctx_coverage", 0.0) or 0.0) > float(low.get("plan_seg_ctx_coverage", 0.0) or 0.0)

        filtered = client.get(
            "/api/run_packages",
            params={"require_plan_ctx_used": "true", "min_plan_seg_ctx_coverage": 0.5, "limit": 100},
        )
        assert filtered.status_code == 200, filtered.text
        filtered_items = filtered.json().get("items", [])
        assert any(item.get("runId") == run_b for item in filtered_items)
        assert all(item.get("runId") != run_a for item in filtered_items)

        shutil.rmtree(dir_a, ignore_errors=True)
        shutil.rmtree(dir_b, ignore_errors=True)
