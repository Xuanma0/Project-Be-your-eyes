from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from byes.inference.backends.http import HttpDepthBackend
from main import app, gateway


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_health(url: str, timeout_sec: float = 20.0) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            response = httpx.get(url, timeout=1.0)
            if response.status_code == 200:
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)
    raise RuntimeError(f"service_not_ready:{url}")


def _encode_test_png() -> bytes:
    image = Image.new("RGB", (16, 16), (24, 48, 72))
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


def test_da3_ref_view_strategy_passthrough_fixture(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_root = tests_dir.parent
    fixture_dir = tests_dir / "fixtures" / "run_package_with_da3_fixture_depth_min"

    da3_port = _pick_port()
    inf_port = _pick_port()
    da3_log = tmp_path / "da3_depth_service.log"
    inf_log = tmp_path / "inference_service_depth.log"

    da3_proc: subprocess.Popen[bytes] | None = None
    inf_proc: subprocess.Popen[bytes] | None = None
    da3_log_file: Any | None = None
    inf_log_file: Any | None = None

    original_enable_depth = gateway.config.inference_enable_depth
    original_enable_seg = gateway.config.inference_enable_seg
    original_enable_ocr = gateway.config.inference_enable_ocr
    original_enable_risk = gateway.config.inference_enable_risk
    original_depth_backend = gateway.depth_backend
    original_scheduler_seq = int(getattr(gateway.scheduler, "_seq", 0))
    original_scheduler_latest_seq = int(getattr(gateway.scheduler, "_latest_seq", 0))

    try:
        da3_env = dict(os.environ)
        da3_env["BYES_DA3_MODE"] = "fixture"
        da3_env["BYES_DA3_FIXTURE_DIR"] = str(fixture_dir)
        da3_env["BYES_DA3_MODEL_ID"] = "da3-v1-fixture"
        da3_proc, da3_log_file = _start_uvicorn(
            module_path="services.da3_depth_service.app:app",
            gateway_root=gateway_root,
            port=da3_port,
            env=da3_env,
            log_path=da3_log,
        )
        _wait_health(f"http://127.0.0.1:{da3_port}/healthz")

        inf_env = dict(os.environ)
        inf_env["BYES_SERVICE_DEPTH_PROVIDER"] = "http"
        inf_env["BYES_SERVICE_DEPTH_ENDPOINT"] = f"http://127.0.0.1:{da3_port}/depth"
        inf_env["BYES_SERVICE_DEPTH_HTTP_DOWNSTREAM"] = "da3"
        inf_env["BYES_SERVICE_DEPTH_HTTP_REF_VIEW_STRATEGY"] = "auto_ref"
        inf_env["BYES_SERVICE_DEPTH_MODEL_ID"] = "depth-http-da3-ref-view"
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
            object.__setattr__(gateway.config, "inference_enable_depth", True)
            object.__setattr__(gateway.config, "inference_enable_seg", False)
            object.__setattr__(gateway.config, "inference_enable_ocr", False)
            object.__setattr__(gateway.config, "inference_enable_risk", False)
            gateway.depth_backend = HttpDepthBackend(
                url=f"http://127.0.0.1:{inf_port}/depth",
                timeout_ms=2000,
                model_id="depth-http-da3-ref-view",
            )
            setattr(gateway.scheduler, "_seq", 0)
            setattr(gateway.scheduler, "_latest_seq", 0)
            gateway.drain_inference_events()

            image_bytes = _encode_test_png()
            response = client.post(
                "/api/frame",
                files={"image": ("frame_1.png", image_bytes, "image/png")},
                data={"meta": "{\"runId\":\"fixture-da3-depth\",\"sessionId\":\"fixture-da3-depth\",\"frameSeq\":1}"},
            )
            assert response.status_code == 200, response.text

        rows = gateway.drain_inference_events()
        depth_rows = [
            row
            for row in rows
            if isinstance(row, dict)
            and str(row.get("name", "")).strip() == "depth.estimate"
            and str(row.get("phase", "")).strip() == "result"
            and str(row.get("status", "")).strip() == "ok"
        ]
        assert depth_rows
        payload = depth_rows[-1].get("payload")
        payload = payload if isinstance(payload, dict) else {}
        meta = payload.get("meta")
        meta = meta if isinstance(meta, dict) else {}
        assert str(meta.get("refViewStrategy", "")).strip() == "auto_ref"
    finally:
        _stop_process(inf_proc, inf_log_file)
        _stop_process(da3_proc, da3_log_file)
        object.__setattr__(gateway.config, "inference_enable_depth", original_enable_depth)
        object.__setattr__(gateway.config, "inference_enable_seg", original_enable_seg)
        object.__setattr__(gateway.config, "inference_enable_ocr", original_enable_ocr)
        object.__setattr__(gateway.config, "inference_enable_risk", original_enable_risk)
        gateway.depth_backend = original_depth_backend
        setattr(gateway.scheduler, "_seq", original_scheduler_seq)
        setattr(gateway.scheduler, "_latest_seq", original_scheduler_latest_seq)
        gateway.drain_inference_events()
