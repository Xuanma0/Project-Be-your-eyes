from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


def test_api_pov_context_endpoint_run_package_and_event_log(tmp_path: Path) -> None:
    fixture_src = Path(__file__).resolve().parent / "fixtures" / "pov_ir_v1_min"
    run_pkg = tmp_path / "pov_ctx_runpkg"
    shutil.copytree(fixture_src, run_pkg)
    events_path = run_pkg / "events" / "events_v1.jsonl"

    with TestClient(app) as client:
        response = client.post(
            "/api/pov/context",
            json={
                "runPackage": str(run_pkg),
                "budget": {"maxChars": 180, "maxTokensApprox": 50},
                "mode": "decisions_plus_highlights",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload.get("schemaVersion") == "pov.context.v1"
        assert isinstance(payload.get("stats"), dict)
        stats = payload["stats"]
        assert isinstance(stats.get("in"), dict)
        assert isinstance(stats.get("out"), dict)
        assert isinstance(stats.get("truncation"), dict)
        prompt = payload.get("text", {}).get("prompt", "")
        assert isinstance(prompt, str) and prompt
        assert len(prompt) <= 180

    rows: list[dict] = []
    with events_path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    assert any(str(row.get("name", "")) == "pov.context" for row in rows)
