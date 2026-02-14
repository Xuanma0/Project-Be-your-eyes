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
from fastapi.testclient import TestClient
from PIL import Image

from byes.inference.backends.http import HttpSegBackend
from main import app, gateway


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


def test_seg_prompt_mask_http_reference_e2e(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_root = tests_dir.parent
    fixture_src = tests_dir / "fixtures" / "run_package_with_seg_prompt_and_mask_gt_min"
    run_pkg = tmp_path / "run_pkg_seg_prompt_mask_e2e"
    shutil.copytree(fixture_src, run_pkg)

    ref_port = _pick_port()
    inf_port = _pick_port()
    ref_log = tmp_path / "reference_seg_service_prompt_mask.log"
    inf_log = tmp_path / "inference_service_prompt_mask.log"

    ref_proc: subprocess.Popen[bytes] | None = None
    inf_proc: subprocess.Popen[bytes] | None = None
    ref_log_file: Any | None = None
    inf_log_file: Any | None = None

    original_enable_seg = gateway.config.inference_enable_seg
    original_enable_ocr = gateway.config.inference_enable_ocr
    original_enable_risk = gateway.config.inference_enable_risk
    original_seg_targets = gateway.config.inference_seg_targets
    original_seg_prompt = gateway.config.inference_seg_prompt
    original_seg_backend = gateway.seg_backend
    original_scheduler_seq = int(getattr(gateway.scheduler, "_seq", 0))
    original_scheduler_latest_seq = int(getattr(gateway.scheduler, "_latest_seq", 0))

    try:
        ref_env = dict(os.environ)
        ref_env["BYES_REF_SEG_FIXTURE_DIR"] = str(run_pkg)
        ref_env["BYES_REF_SEG_RUN_ID"] = "fixture-seg-prompt-mask"
        ref_proc, ref_log_file = _start_uvicorn(
            module_path="services.reference_seg_service.app:app",
            gateway_root=gateway_root,
            port=ref_port,
            env=ref_env,
            log_path=ref_log,
        )
        _wait_health(f"http://127.0.0.1:{ref_port}/healthz")

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

        with TestClient(app) as client:
            reset = client.post("/api/dev/reset")
            assert reset.status_code == 200, reset.text
            object.__setattr__(gateway.config, "inference_enable_seg", True)
            object.__setattr__(gateway.config, "inference_enable_ocr", False)
            object.__setattr__(gateway.config, "inference_enable_risk", False)
            object.__setattr__(gateway.config, "inference_seg_targets", ())
            object.__setattr__(
                gateway.config,
                "inference_seg_prompt",
                {
                    "schemaVersion": "byes.seg_request.v1",
                    "targets": ["person"],
                    "text": "find person only",
                    "meta": {"promptVersion": "v1"},
                },
            )
            gateway.seg_backend = HttpSegBackend(
                url=f"http://127.0.0.1:{inf_port}/seg",
                timeout_ms=2500,
                model_id="seg-http-prompt-mask-e2e",
            )
            setattr(gateway.scheduler, "_seq", 0)
            setattr(gateway.scheduler, "_latest_seq", 0)
            gateway.drain_inference_events()
            image_bytes = _encode_test_png()
            for frame_seq in (1, 2):
                frame_path = run_pkg / "frames" / f"frame_{frame_seq}.png"
                meta = json.dumps(
                    {
                        "runId": "fixture-seg-prompt-mask",
                        "sessionId": "fixture-seg-prompt-mask",
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
        prompt_rows = [
            row
            for row in events
            if isinstance(row, dict)
            and str(row.get("name", "")).strip() == "seg.prompt"
            and str(row.get("phase", "")).strip() == "result"
            and str(row.get("status", "")).strip() == "ok"
        ]
        seg_rows = [
            row
            for row in events
            if isinstance(row, dict)
            and str(row.get("name", "")).strip() == "seg.segment"
            and str(row.get("phase", "")).strip() == "result"
            and str(row.get("status", "")).strip() == "ok"
        ]
        assert len(prompt_rows) >= 2
        assert len(seg_rows) >= 2

        for row in seg_rows:
            payload = row.get("payload", {})
            assert isinstance(payload, dict)
            segments = payload.get("segments")
            assert isinstance(segments, list)
            assert len(segments) == 1
            segment = segments[0]
            assert isinstance(segment, dict)
            assert str(segment.get("label", "")).strip().lower() == "person"
            mask = segment.get("mask")
            assert isinstance(mask, dict)
            assert str(mask.get("format", "")).strip() == "rle_v1"
            size = mask.get("size")
            counts = mask.get("counts")
            assert isinstance(size, list) and len(size) == 2
            assert isinstance(counts, list)
            assert int(size[0]) * int(size[1]) == sum(int(v) for v in counts)

        events_path = run_pkg / "events" / "events_v1.jsonl"
        events_path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in events if isinstance(item, dict)) + "\n",
            encoding="utf-8",
        )

        report_script = gateway_root / "scripts" / "report_run.py"
        report_md = tmp_path / "report_seg_prompt_mask_http_e2e.md"
        report_json = tmp_path / "report_seg_prompt_mask_http_e2e.json"
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
        assert float(seg.get("maskCoverage", 0.0)) == 1.0
        assert int(seg.get("maskFramesWithGt", 0)) == 2
        assert int(seg.get("maskFramesWithPred", 0)) == 2
    finally:
        _stop_process(inf_proc, inf_log_file)
        _stop_process(ref_proc, ref_log_file)
        object.__setattr__(gateway.config, "inference_enable_seg", original_enable_seg)
        object.__setattr__(gateway.config, "inference_enable_ocr", original_enable_ocr)
        object.__setattr__(gateway.config, "inference_enable_risk", original_enable_risk)
        object.__setattr__(gateway.config, "inference_seg_targets", original_seg_targets)
        object.__setattr__(gateway.config, "inference_seg_prompt", original_seg_prompt)
        gateway.seg_backend = original_seg_backend
        setattr(gateway.scheduler, "_seq", original_scheduler_seq)
        setattr(gateway.scheduler, "_latest_seq", original_scheduler_latest_seq)
        gateway.drain_inference_events()
