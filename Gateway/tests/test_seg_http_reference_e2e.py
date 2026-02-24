from __future__ import annotations

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


def test_seg_http_reference_service_e2e(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_root = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_seg_gt_min"
    run_pkg = tmp_path / "run_pkg_seg_e2e"
    shutil.copytree(fixture_src, run_pkg)

    ref_port = _pick_port()
    inf_port = _pick_port()
    ref_log = tmp_path / "reference_seg_service.log"
    inf_log = tmp_path / "inference_service.log"

    ref_proc: subprocess.Popen[bytes] | None = None
    inf_proc: subprocess.Popen[bytes] | None = None
    ref_log_file: Any | None = None
    inf_log_file: Any | None = None

    original_enable_seg = gateway.config.inference_enable_seg
    original_enable_ocr = gateway.config.inference_enable_ocr
    original_enable_risk = gateway.config.inference_enable_risk
    original_seg_targets = gateway.config.inference_seg_targets
    original_seg_backend = gateway.seg_backend
    original_scheduler_seq = int(getattr(gateway.scheduler, "_seq", 0))
    original_scheduler_latest_seq = int(getattr(gateway.scheduler, "_latest_seq", 0))

    try:
        ref_env = dict(os.environ)
        ref_env["BYES_REF_SEG_FIXTURE_PATH"] = str(run_pkg / "gt" / "seg_gt_v1.json")
        ref_env["BYES_REF_SEG_RUN_ID"] = "fixture-seg-gt"
        ref_proc, ref_log_file = _start_uvicorn(
            module_path="services.reference_seg_service.app:app",
            gateway_root=gateway_root,
            port=ref_port,
            env=ref_env,
            log_path=ref_log,
        )
        _wait_health(f"http://127.0.0.1:{ref_port}/healthz")
        schema_path = gateway_root / "contracts" / "byes.seg.v1.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
        ref_probe = httpx.post(
            f"http://127.0.0.1:{ref_port}/seg",
            json={"runId": "fixture-seg-gt", "frameSeq": 1, "image_b64": ""},
            timeout=3.0,
        )
        assert ref_probe.status_code == 200, ref_probe.text
        ref_payload = ref_probe.json()
        jsonschema.validate(ref_payload, schema)

        inf_env = dict(os.environ)
        inf_env["BYES_SERVICE_SEG_PROVIDER"] = "http"
        inf_env["BYES_SERVICE_SEG_ENDPOINT"] = f"http://127.0.0.1:{ref_port}/seg"
        inf_env["BYES_SERVICE_SEG_MODEL_ID"] = "reference-seg-v1"
        inf_proc, inf_log_file = _start_uvicorn(
            module_path="services.inference_service.app:app",
            gateway_root=gateway_root,
            port=inf_port,
            env=inf_env,
            log_path=inf_log,
        )
        _wait_health(f"http://127.0.0.1:{inf_port}/healthz")

        object.__setattr__(gateway.config, "inference_enable_seg", True)
        object.__setattr__(gateway.config, "inference_enable_ocr", False)
        object.__setattr__(gateway.config, "inference_enable_risk", False)
        object.__setattr__(gateway.config, "inference_seg_targets", ("person", "chair"))
        gateway.seg_backend = HttpSegBackend(
            url=f"http://127.0.0.1:{inf_port}/seg",
            timeout_ms=2000,
            model_id="seg-http-e2e",
        )
        setattr(gateway.scheduler, "_seq", 0)
        setattr(gateway.scheduler, "_latest_seq", 0)

        gateway.drain_inference_events()
        with TestClient(app) as client:
            reset = client.post("/api/dev/reset")
            assert reset.status_code == 200, reset.text
            for frame_seq in (1, 2):
                frame_path = run_pkg / "frames" / f"frame_{frame_seq}.png"
                meta = json.dumps({"runId": "fixture-seg-gt", "sessionId": "fixture-seg-gt", "frameSeq": frame_seq})
                with frame_path.open("rb") as fp:
                    response = client.post(
                        "/api/frame",
                        files={"image": (frame_path.name, fp.read(), "image/png")},
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
        for row in seg_rows[:2]:
            payload = row.get("payload", {})
            assert isinstance(payload, dict)
            assert isinstance(payload.get("segments"), list)
            assert int(payload.get("targetsCount", 0)) == 2
            assert payload.get("targetsUsed") == ["person", "chair"]

        events_path = run_pkg / "events" / "events_v1.jsonl"
        events_path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in events if isinstance(item, dict)) + "\n",
            encoding="utf-8",
        )

        report_script = gateway_root / "scripts" / "report_run.py"
        report_md = tmp_path / "report_seg_http_e2e.md"
        report_json = tmp_path / "report_seg_http_e2e.json"
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
        seg = quality.get("seg", {})
        assert isinstance(seg, dict)
        assert bool(seg.get("present")) is True
        assert float(seg.get("coverage", 0.0)) == 1.0
    finally:
        _stop_process(inf_proc, inf_log_file)
        _stop_process(ref_proc, ref_log_file)
        object.__setattr__(gateway.config, "inference_enable_seg", original_enable_seg)
        object.__setattr__(gateway.config, "inference_enable_ocr", original_enable_ocr)
        object.__setattr__(gateway.config, "inference_enable_risk", original_enable_risk)
        object.__setattr__(gateway.config, "inference_seg_targets", original_seg_targets)
        gateway.seg_backend = original_seg_backend
        setattr(gateway.scheduler, "_seq", original_scheduler_seq)
        setattr(gateway.scheduler, "_latest_seq", original_scheduler_latest_seq)
        gateway.drain_inference_events()
