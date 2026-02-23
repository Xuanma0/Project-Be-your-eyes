from __future__ import annotations

import io
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


def test_api_slam_context_endpoint_returns_context() -> None:
    fixture_name = "run_package_with_slam_context_min"
    with TestClient(app) as client:
        payload = _zip_fixture_bytes(fixture_name)
        response = client.post(
            "/api/run_package/upload",
            files={"file": (f"{fixture_name}.zip", payload, "application/zip")},
            data={"scenarioTag": "slam_context_api_test"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        run_id = str(body["runId"])
        run_dir = Path(body["runDir"])

        ctx_resp = client.get(
            "/api/slam/context",
            params={"runId": run_id, "maxChars": 256, "mode": "last_pose_and_health"},
        )
        assert ctx_resp.status_code == 200, ctx_resp.text
        ctx = ctx_resp.json()
        assert ctx.get("schemaVersion") == "slam.context.v1"
        assert ctx.get("runId")
        assert isinstance(ctx.get("health"), dict)
        assert isinstance(ctx.get("stats"), dict)
        prompt = str(ctx.get("text", {}).get("promptFragment", ""))
        assert prompt.strip()
        assert int(ctx.get("text", {}).get("promptFragmentLength", 0) or 0) == len(prompt)

        shutil.rmtree(run_dir, ignore_errors=True)
