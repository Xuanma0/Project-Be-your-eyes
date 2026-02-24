from __future__ import annotations

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from byes.inference.backends.http import HttpSegBackend
from main import app, gateway

jsonschema = pytest.importorskip("jsonschema")


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_health(url: str, timeout_sec: float = 20.0) -> None:
    deadline = time.time() + timeout_sec
    last_error: str | None = None
    while time.time() < deadline:
        try:
            response = httpx.get(url, timeout=1.0)
            if response.status_code == 200:
                return
            last_error = f"http_{response.status_code}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc.__class__.__name__)
        time.sleep(0.2)
    raise RuntimeError(f"service_not_ready:{url}:{last_error}")


def _encode_test_png() -> bytes:
    image = Image.new("RGB", (16, 16), (64, 96, 128))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _start_uvicorn(
    *,
    module_path: str,
    gateway_root: Path,
    port: int,
    env: dict[str, str],
    log_path: Path,
) -> tuple[subprocess.Popen[bytes], Any]:
    log_file = log_path.open("w", encoding="utf-8")
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        module_path,
        "--app-dir",
        str(gateway_root),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=gateway_root.parent,
        env=env,
        stdout=log_file,
        stderr=log_file,
    )
    return proc, log_file


def _stop_process(proc: subprocess.Popen[bytes] | None, log_file: Any | None) -> None:
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()
    if log_file is not None:
        log_file.close()


def test_seg_http_sam3_tracking_fixture_service_e2e(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_root = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_sam3_tracking_fixture_seg_min"
    run_pkg = tmp_path / "run_pkg_seg_sam3_tracking_e2e"
    shutil.copytree(fixture_src, run_pkg)

    sam3_port = _pick_port()
    inf_port = _pick_port()
    sam3_log = tmp_path / "sam3_seg_service_tracking.log"
    inf_log = tmp_path / "inference_service_tracking.log"

    sam3_proc: subprocess.Popen[bytes] | None = None
    inf_proc: subprocess.Popen[bytes] | None = None
    sam3_log_file: Any | None = None
    inf_log_file: Any | None = None

    original_enable_seg = gateway.config.inference_enable_seg
    original_enable_ocr = gateway.config.inference_enable_ocr
    original_enable_risk = gateway.config.inference_enable_risk
    original_seg_targets = gateway.config.inference_seg_targets
    original_seg_tracking = gateway.config.inference_seg_tracking
    original_seg_backend = gateway.seg_backend
    original_scheduler_seq = int(getattr(gateway.scheduler, "_seq", 0))
    original_scheduler_latest_seq = int(getattr(gateway.scheduler, "_latest_seq", 0))

    try:
        sam3_env = dict(os.environ)
        sam3_env["BYES_SAM3_MODE"] = "fixture"
        sam3_env["BYES_SAM3_FIXTURE_DIR"] = str(run_pkg)
        sam3_env["BYES_SAM3_MODEL_ID"] = "sam3-v1-fixture"
        sam3_proc, sam3_log_file = _start_uvicorn(
            module_path="services.sam3_seg_service.app:app",
            gateway_root=gateway_root,
            port=sam3_port,
            env=sam3_env,
            log_path=sam3_log,
        )
        _wait_health(f"http://127.0.0.1:{sam3_port}/healthz")

        schema_path = gateway_root / "contracts" / "byes.seg.v1.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
        sam3_probe = httpx.post(
            f"http://127.0.0.1:{sam3_port}/seg",
            json={"runId": "fixture-sam3-tracking", "frameSeq": 1, "image_b64": "", "tracking": True},
            timeout=3.0,
        )
        assert sam3_probe.status_code == 200, sam3_probe.text
        sam3_payload = sam3_probe.json()
        jsonschema.validate(sam3_payload, schema)
        sam3_segments = sam3_payload.get("segments", [])
        assert isinstance(sam3_segments, list) and sam3_segments
        assert isinstance(sam3_segments[0].get("trackId"), str)

        inf_env = dict(os.environ)
        inf_env["BYES_SERVICE_SEG_PROVIDER"] = "http"
        inf_env["BYES_SERVICE_SEG_ENDPOINT"] = f"http://127.0.0.1:{sam3_port}/seg"
        inf_env["BYES_SERVICE_SEG_HTTP_DOWNSTREAM"] = "sam3"
        inf_env["BYES_SERVICE_SEG_HTTP_TRACKING"] = "1"
        inf_env["BYES_SERVICE_SEG_MODEL_ID"] = "sam3-v1-fixture"
        inf_proc, inf_log_file = _start_uvicorn(
            module_path="services.inference_service.app:app",
            gateway_root=gateway_root,
            port=inf_port,
            env=inf_env,
            log_path=inf_log,
        )
        _wait_health(f"http://127.0.0.1:{inf_port}/healthz")

        with TestClient(app) as client:
            reset = client.post("/api/dev/reset")
            assert reset.status_code == 200, reset.text
            object.__setattr__(gateway.config, "inference_enable_seg", True)
            object.__setattr__(gateway.config, "inference_enable_ocr", False)
            object.__setattr__(gateway.config, "inference_enable_risk", False)
            object.__setattr__(gateway.config, "inference_seg_targets", ())
            object.__setattr__(gateway.config, "inference_seg_tracking", True)
            gateway.seg_backend = HttpSegBackend(
                url=f"http://127.0.0.1:{inf_port}/seg",
                timeout_ms=2000,
                model_id="seg-http-sam3-tracking-e2e",
            )
            setattr(gateway.scheduler, "_seq", 0)
            setattr(gateway.scheduler, "_latest_seq", 0)
            gateway.drain_inference_events()
            image_bytes = _encode_test_png()
            for frame_seq in (1, 2):
                frame_path = run_pkg / "frames" / f"frame_{frame_seq}.png"
                meta = json.dumps(
                    {
                        "runId": "fixture-sam3-tracking",
                        "sessionId": "fixture-sam3-tracking",
                        "frameSeq": frame_seq,
                    }
                )
                response = client.post(
                    "/api/frame",
                    files={"image": (frame_path.name, image_bytes, "image/png")},
                    data={"meta": meta},
                )
                assert response.status_code == 200, response.text

        events = gateway.drain_inference_events()
        seg_rows = [
            row
            for row in events
            if isinstance(row, dict)
            and str(row.get("name", "")).strip() == "seg.segment"
            and str(row.get("phase", "")).strip() == "result"
            and str(row.get("status", "")).strip() == "ok"
        ]
        assert len(seg_rows) >= 2

        by_frame_track_ids: dict[int, set[str]] = {}
        for row in seg_rows:
            payload = row.get("payload", {})
            assert isinstance(payload, dict)
            frame_seq = int(row.get("frameSeq", 0) or 0)
            segments = payload.get("segments")
            assert isinstance(segments, list)
            track_ids = {
                str(seg.get("trackId")).strip()
                for seg in segments
                if isinstance(seg, dict) and isinstance(seg.get("trackId"), str) and str(seg.get("trackId")).strip()
            }
            if frame_seq > 0:
                by_frame_track_ids[frame_seq] = track_ids
        assert by_frame_track_ids.get(1)
        assert by_frame_track_ids.get(2)
        assert by_frame_track_ids[1].intersection(by_frame_track_ids[2]), json.dumps(seg_rows, ensure_ascii=False)

        events_path = run_pkg / "events" / "events_v1.jsonl"
        events_path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in events if isinstance(item, dict)) + "\n",
            encoding="utf-8",
        )

        report_script = gateway_root / "scripts" / "report_run.py"
        report_md = tmp_path / "report_seg_http_sam3_tracking_e2e.md"
        report_json = tmp_path / "report_seg_http_sam3_tracking_e2e.json"
        result = subprocess.run(
            [
                sys.executable,
                str(report_script),
                "--run-package",
                str(run_pkg),
                "--output",
                str(report_md),
                "--output-json",
                str(report_json),
            ],
            cwd=gateway_root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        payload = json.loads(report_json.read_text(encoding="utf-8-sig"))
        quality = payload.get("quality", {})
        seg_tracking = quality.get("segTracking", {})
        assert isinstance(seg_tracking, dict)
        assert bool(seg_tracking.get("present")) is True
        assert float(seg_tracking.get("trackCoverage", 0.0)) > 0.0
    finally:
        _stop_process(inf_proc, inf_log_file)
        _stop_process(sam3_proc, sam3_log_file)
        object.__setattr__(gateway.config, "inference_enable_seg", original_enable_seg)
        object.__setattr__(gateway.config, "inference_enable_ocr", original_enable_ocr)
        object.__setattr__(gateway.config, "inference_enable_risk", original_enable_risk)
        object.__setattr__(gateway.config, "inference_seg_targets", original_seg_targets)
        object.__setattr__(gateway.config, "inference_seg_tracking", original_seg_tracking)
        gateway.seg_backend = original_seg_backend
        setattr(gateway.scheduler, "_seq", original_scheduler_seq)
        setattr(gateway.scheduler, "_latest_seq", original_scheduler_latest_seq)
        gateway.drain_inference_events()
