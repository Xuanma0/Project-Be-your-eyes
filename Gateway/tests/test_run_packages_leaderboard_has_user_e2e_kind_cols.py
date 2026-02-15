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
        files={"file": ("frame_user_e2e_kind_cols.zip", payload, "application/zip")},
        data={"scenarioTag": tag},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return str(body["runId"]), Path(body["runDir"])


def _set_frame_user_e2e_kind_metrics(
    report_path: Path,
    *,
    tts_p90: int,
    tts_max: int,
    ar_p90: int,
    ar_max: int,
    diversity: int,
) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    by_kind: dict[str, object] = {}
    if diversity >= 1:
        by_kind["tts"] = {
            "count": 2,
            "coverageRatio": 1.0,
            "totalMs": {"count": 2, "p50": int(tts_p90 // 2), "p90": int(tts_p90), "p99": int(tts_max), "max": int(tts_max), "valuesSample": [int(tts_p90 // 2), int(tts_p90)]},
        }
    if diversity >= 2:
        by_kind["ar"] = {
            "count": 1,
            "coverageRatio": 0.5,
            "totalMs": {"count": 1, "p50": int(ar_p90), "p90": int(ar_p90), "p99": int(ar_max), "max": int(ar_max), "valuesSample": [int(ar_p90)]},
        }

    payload["frameUserE2E"] = {
        "present": True,
        "events": 2,
        "coverage": {"framesWithInputDeclared": 2, "framesWithAck": 2, "ratio": 1.0},
        "totalMs": {"count": 2, "p50": 120, "p90": 220, "p99": 260, "max": 260, "valuesSample": [120, 220]},
        "byKind": by_kind,
        "tts": {"count": 2, "coverageRatio": 1.0, "p50": int(tts_p90 // 2), "p90": int(tts_p90), "max": int(tts_max)},
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_packages_leaderboard_has_user_e2e_kind_cols() -> None:
    with TestClient(app) as client:
        run_low, dir_low = _upload(client, "frame_user_e2e_kind_low")
        run_high, dir_high = _upload(client, "frame_user_e2e_kind_high")

        _set_frame_user_e2e_kind_metrics(
            dir_low / "report.json",
            tts_p90=120,
            tts_max=160,
            ar_p90=210,
            ar_max=210,
            diversity=1,
        )
        _set_frame_user_e2e_kind_metrics(
            dir_high / "report.json",
            tts_p90=280,
            tts_max=300,
            ar_p90=180,
            ar_max=240,
            diversity=2,
        )

        rows = client.get("/api/run_packages", params={"sort": "frame_user_e2e_tts_p90", "order": "desc", "limit": 100})
        assert rows.status_code == 200, rows.text
        items = rows.json().get("items", [])
        high = next((item for item in items if item.get("runId") == run_high), None)
        low = next((item for item in items if item.get("runId") == run_low), None)
        assert isinstance(high, dict)
        assert isinstance(low, dict)
        for key in (
            "frame_user_e2e_tts_p90",
            "frame_user_e2e_tts_max",
            "frame_user_e2e_ar_p90",
            "frame_user_e2e_ar_max",
            "ack_kind_diversity",
        ):
            assert key in high
        assert int(high.get("frame_user_e2e_tts_p90", 0) or 0) > int(low.get("frame_user_e2e_tts_p90", 0) or 0)

        filtered_tts = client.get("/api/run_packages", params={"max_frame_user_e2e_tts_p90": 200, "limit": 100})
        assert filtered_tts.status_code == 200, filtered_tts.text
        filtered_tts_items = filtered_tts.json().get("items", [])
        assert any(item.get("runId") == run_low for item in filtered_tts_items)
        assert all(item.get("runId") != run_high for item in filtered_tts_items)

        filtered_diversity = client.get("/api/run_packages", params={"min_ack_kind_diversity": 2, "limit": 100})
        assert filtered_diversity.status_code == 200, filtered_diversity.text
        filtered_diversity_items = filtered_diversity.json().get("items", [])
        assert any(item.get("runId") == run_high for item in filtered_diversity_items)
        assert all(item.get("runId") != run_low for item in filtered_diversity_items)

        shutil.rmtree(dir_low, ignore_errors=True)
        shutil.rmtree(dir_high, ignore_errors=True)
