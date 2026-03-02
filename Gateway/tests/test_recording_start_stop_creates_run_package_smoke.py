from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi.testclient import TestClient

from main import app, gateway


def test_recording_start_stop_creates_run_package(tmp_path: Path) -> None:
    original_root = gateway.run_packages_root
    gateway.run_packages_root = tmp_path / "run_packages"
    gateway.recording = gateway.recording.__class__(run_packages_root=gateway.run_packages_root)
    gateway.recording.reset()
    gateway.drain_inference_events()

    try:
        with TestClient(app) as client:
            start_resp = client.post(
                "/api/record/start",
                json={
                    "deviceId": "quest-record-device",
                    "note": "record smoke",
                    "maxSec": 60,
                    "maxFrames": 10,
                },
            )
            assert start_resp.status_code == 200
            start_payload = start_resp.json()
            assert start_payload["ok"] is True
            assert start_payload["deviceId"] == "quest-record-device"

            meta = json.dumps(
                {
                    "runId": "quest-record-run",
                    "deviceId": "quest-record-device",
                    "captureTsMs": 123456,
                    "mode": "walk",
                }
            )
            files = {"image": ("frame.jpg", io.BytesIO(b"fake_jpeg_bytes"), "image/jpeg")}
            frame_resp = client.post("/api/frame", files=files, data={"meta": meta})
            assert frame_resp.status_code == 200

            stop_resp = client.post("/api/record/stop", json={"deviceId": "quest-record-device"})
            assert stop_resp.status_code == 200
            stop_payload = stop_resp.json()
            assert stop_payload["ok"] is True
            assert stop_payload["framesCount"] >= 1

            root = Path(stop_payload["recordingPath"])
            assert root.exists()
            assert (root / "manifest.json").exists()
            assert (root / "frames_meta.jsonl").exists()
            assert (root / "events" / "events_v1.jsonl").exists()

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            assert manifest.get("scenarioTag") == "quest_recording"
            assert int(manifest.get("framesCount", 0)) >= 1
            assert str(manifest.get("framesDir", "")) == "frames"
    finally:
        gateway.run_packages_root = original_root
        gateway.recording = gateway.recording.__class__(run_packages_root=gateway.run_packages_root)
        gateway.recording.reset()
        gateway.drain_inference_events()
