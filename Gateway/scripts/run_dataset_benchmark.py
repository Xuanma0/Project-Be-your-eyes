from __future__ import annotations

import argparse
import csv
import json
import os
import random
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent
REPO_ROOT = GATEWAY_ROOT.parent


@dataclass
class ServiceSpec:
    name: str
    module: str
    port: int
    health_path: str
    env: dict[str, str]


@dataclass
class ServiceRuntime:
    spec: ServiceSpec
    process: subprocess.Popen[str] | None
    reused: bool


def _now_ms() -> int:
    return int(time.time() * 1000)


def _utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _parse_bool(raw: str | int | bool) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return raw != 0
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _parse_ports(raw: str) -> dict[str, int]:
    defaults = {
        "gateway": 19090,
        "inference": 19100,
        "seg": 19120,
        "depth": 19121,
        "ocr": 19122,
        "sam3": 19130,
        "da3": 19131,
    }
    text = str(raw or "").strip()
    if not text:
        return defaults
    out = dict(defaults)
    for chunk in text.split(","):
        part = chunk.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        if key not in out:
            continue
        try:
            port = int(value.strip())
        except Exception:
            continue
        if port <= 0:
            continue
        out[key] = port
    return out


def _parse_services(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    text = str(raw or "").strip()
    if not text:
        return out
    for chunk in text.split(","):
        part = chunk.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        name = key.strip().lower()
        val = value.strip().lower()
        if name in {"seg", "depth", "ocr"} and val in {"reference", "sam3", "da3"}:
            out[name] = val
    return out


def _load_env_file(path: Path | None) -> dict[str, str]:
    env: dict[str, str] = {}
    if path is None:
        return env
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"env file not found: {path}")
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _discover_run_packages(root: Path, glob_pattern: str) -> list[Path]:
    manifests: list[Path] = []
    pattern = str(glob_pattern or "").strip() or "*/manifest.json"
    for p in root.glob(pattern):
        if p.is_file() and p.name in {"manifest.json", "run_manifest.json"}:
            manifests.append(p)
    # Always include fallback recursive manifests in case glob is too narrow.
    if not manifests:
        for name in ("manifest.json", "run_manifest.json"):
            manifests.extend(path for path in root.rglob(name) if path.is_file())
    packages = sorted({p.parent.resolve() for p in manifests}, key=lambda path: str(path).lower())
    return packages


def _manifest_for_run_package(run_package: Path) -> dict[str, Any]:
    for name in ("manifest.json", "run_manifest.json"):
        path = run_package / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            return payload
    return {}


def _has_frames(run_package: Path, manifest: dict[str, Any]) -> bool:
    frames_rel = str(manifest.get("framesDir", "")).strip() or "frames"
    frames_dir = run_package / frames_rel
    return frames_dir.exists() and frames_dir.is_dir()


def _slug_from_path(path: Path, root: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
        text = rel.as_posix()
    except Exception:
        text = path.name
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)
    return safe.strip("_") or path.name


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _nested_get(obj: Any, path: list[str], default: Any = None) -> Any:
    cur = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur.get(key)
    return cur


def _collect_summary_fields(*, run_package: Path, manifest: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    quality = report.get("quality")
    quality = quality if isinstance(quality, dict) else {}
    seg = quality.get("seg")
    seg = seg if isinstance(seg, dict) else {}
    depth = quality.get("depth")
    depth = depth if isinstance(depth, dict) else {}
    ocr = quality.get("ocr")
    ocr = ocr if isinstance(ocr, dict) else {}
    slam = quality.get("slam")
    slam = slam if isinstance(slam, dict) else {}
    plan_quality = report.get("planQuality")
    plan_quality = plan_quality if isinstance(plan_quality, dict) else {}
    plan_eval = report.get("planEval")
    plan_eval = plan_eval if isinstance(plan_eval, dict) else {}
    confirm_eval = plan_eval.get("confirm")
    confirm_eval = confirm_eval if isinstance(confirm_eval, dict) else {}
    risk_latency = quality.get("riskLatencyMs")
    risk_latency = risk_latency if isinstance(risk_latency, dict) else {}
    frame_e2e = report.get("frameE2E")
    frame_e2e = frame_e2e if isinstance(frame_e2e, dict) else {}
    frame_e2e_total = frame_e2e.get("totalMs")
    frame_e2e_total = frame_e2e_total if isinstance(frame_e2e_total, dict) else {}
    frame_user = report.get("frameUserE2E")
    frame_user = frame_user if isinstance(frame_user, dict) else {}
    tts_bucket = frame_user.get("tts")
    tts_bucket = tts_bucket if isinstance(tts_bucket, dict) else {}
    by_kind = frame_user.get("byKind")
    by_kind = by_kind if isinstance(by_kind, dict) else {}
    ar_bucket = by_kind.get("ar")
    ar_bucket = ar_bucket if isinstance(ar_bucket, dict) else {}
    if isinstance(ar_bucket, dict):
        ar_total = ar_bucket.get("totalMs")
        ar_total = ar_total if isinstance(ar_total, dict) else {}
    else:
        ar_total = {}
    depth_risk = quality.get("depthRisk")
    depth_risk = depth_risk if isinstance(depth_risk, dict) else {}
    critical = depth_risk.get("critical")
    critical = critical if isinstance(critical, dict) else {}

    frames_count = (
        _to_int(manifest.get("framesCount"))
        or _to_int(manifest.get("frameCountSent"))
        or _to_int(report.get("frame_received"))
        or 0
    )
    return {
        "runId": str(manifest.get("runId", "")).strip() or str(manifest.get("sessionId", "")).strip() or run_package.name,
        "framesCount": int(frames_count),
        "qualityScore": _to_float(quality.get("qualityScore") if "qualityScore" in quality else report.get("qualityScore")),
        "critical_fn": _to_int(critical.get("missCriticalCount")),
        "confirm_timeouts": _to_int(confirm_eval.get("timeouts")),
        "riskLatencyP90": _to_int(risk_latency.get("p90")),
        "frame_e2e_p90": _to_int(frame_e2e_total.get("p90")),
        "frame_user_e2e_tts_p90": _to_int(tts_bucket.get("p90")),
        "frame_user_e2e_ar_p90": _to_int(ar_total.get("p90")),
        "seg_f1_50": _to_float(seg.get("f1At50")),
        "seg_mask_f1_50": _to_float(seg.get("maskF1_50")),
        "depth_absRel": _to_float(depth.get("absRel")),
        "ocr_cer": _to_float(ocr.get("cer")),
        "slam_tracking_rate": _to_float(_nested_get(slam, ["tracking", "trackingRate"])),
        "plan_score": _to_float(plan_quality.get("score")),
        "plan_fallback_used": bool(plan_quality.get("fallbackUsed")) if "fallbackUsed" in plan_quality else None,
    }


def _summary_to_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    out = {
        "runPackage": row.get("runPackage"),
        "targetRunPackage": row.get("targetRunPackage"),
        "runId": row.get("runId"),
        "framesCount": row.get("framesCount"),
        "qualityScore": row.get("qualityScore"),
        "critical_fn": row.get("critical_fn"),
        "confirm_timeouts": row.get("confirm_timeouts"),
        "riskLatencyP90": row.get("riskLatencyP90"),
        "frame_e2e_p90": row.get("frame_e2e_p90"),
        "frame_user_e2e_tts_p90": row.get("frame_user_e2e_tts_p90"),
        "frame_user_e2e_ar_p90": row.get("frame_user_e2e_ar_p90"),
        "seg_f1_50": row.get("seg_f1_50"),
        "seg_mask_f1_50": row.get("seg_mask_f1_50"),
        "depth_absRel": row.get("depth_absRel"),
        "ocr_cer": row.get("ocr_cer"),
        "slam_tracking_rate": row.get("slam_tracking_rate"),
        "plan_score": row.get("plan_score"),
        "plan_fallback_used": row.get("plan_fallback_used"),
        "status": row.get("status"),
        "error": row.get("error"),
    }
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "runPackage",
        "targetRunPackage",
        "runId",
        "framesCount",
        "qualityScore",
        "critical_fn",
        "confirm_timeouts",
        "riskLatencyP90",
        "frame_e2e_p90",
        "frame_user_e2e_tts_p90",
        "frame_user_e2e_ar_p90",
        "seg_f1_50",
        "seg_mask_f1_50",
        "depth_absRel",
        "ocr_cer",
        "slam_tracking_rate",
        "plan_score",
        "plan_fallback_used",
        "status",
        "error",
    ]
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(_summary_to_csv_row(row))


def _write_markdown(path: Path, rows: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# Dataset Benchmark")
    lines.append("")
    lines.append(f"- root: `{payload.get('root', '')}`")
    lines.append(f"- discovered: `{payload.get('discovered', 0)}`")
    lines.append(f"- processed: `{payload.get('processed', 0)}`")
    lines.append(f"- replay: `{payload.get('replay', False)}`")
    lines.append(f"- failures: `{payload.get('failures', 0)}`")
    lines.append("")
    lines.append("| runId | frames | qualityScore | critical_fn | riskP90 | e2eP90 | ttsP90 | arP90 | segF1 | depthAbsRel | ocrCER | slamTrack | status |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for row in rows:
        lines.append(
            "| {run_id} | {frames} | {quality} | {critical_fn} | {risk} | {e2e} | {tts} | {ar} | {seg} | {depth} | {ocr} | {slam} | {status} |".format(
                run_id=row.get("runId"),
                frames=row.get("framesCount"),
                quality=row.get("qualityScore"),
                critical_fn=row.get("critical_fn"),
                risk=row.get("riskLatencyP90"),
                e2e=row.get("frame_e2e_p90"),
                tts=row.get("frame_user_e2e_tts_p90"),
                ar=row.get("frame_user_e2e_ar_p90"),
                seg=row.get("seg_f1_50"),
                depth=row.get("depth_absRel"),
                ocr=row.get("ocr_cer"),
                slam=row.get("slam_tracking_rate"),
                status=row.get("status"),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _http_ready(url: str, timeout_s: float = 2.0) -> bool:
    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.get(url)
            return 200 <= int(resp.status_code) < 500
    except Exception:
        return False


def _start_service(spec: ServiceSpec, *, base_env: dict[str, str], logs_dir: Path) -> ServiceRuntime:
    base_url = f"http://127.0.0.1:{spec.port}"
    health_url = f"{base_url}{spec.health_path}"
    if _http_ready(health_url, timeout_s=1.5):
        return ServiceRuntime(spec=spec, process=None, reused=True)

    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{spec.name}.log"
    env = dict(base_env)
    env.update(spec.env)
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        spec.module,
        "--host",
        "127.0.0.1",
        "--port",
        str(spec.port),
        "--app-dir",
        str(GATEWAY_ROOT),
    ]
    log_fp = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        cwd=REPO_ROOT,
        env=env,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        text=True,
    )
    started = time.time()
    while time.time() - started < 25.0:
        if proc.poll() is not None:
            log_fp.close()
            raise RuntimeError(f"service {spec.name} exited early (code={proc.returncode}) log={log_path}")
        if _http_ready(health_url, timeout_s=1.0):
            return ServiceRuntime(spec=spec, process=proc, reused=False)
        time.sleep(0.25)
    proc.terminate()
    log_fp.close()
    raise TimeoutError(f"service {spec.name} did not become healthy: {health_url}")


def _stop_service(runtime: ServiceRuntime) -> None:
    proc = runtime.process
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8.0)
        except Exception:
            proc.kill()
            proc.wait(timeout=4.0)


def _build_service_specs(
    *,
    ports: dict[str, int],
    services: dict[str, str],
) -> tuple[list[ServiceSpec], dict[str, str], dict[str, str]]:
    # returns (service_specs_to_start, gateway_env_overrides, inference_env_overrides)
    start_specs: list[ServiceSpec] = []
    gateway_env: dict[str, str] = {}
    inference_env: dict[str, str] = {}

    use_seg = "seg" in services
    use_depth = "depth" in services
    use_ocr = "ocr" in services
    needs_inference = use_seg or use_depth or use_ocr

    if use_seg:
        seg_mode = services["seg"]
        if seg_mode == "reference":
            start_specs.append(
                ServiceSpec(
                    name="reference_seg",
                    module="services.reference_seg_service.app:app",
                    port=int(ports["seg"]),
                    health_path="/healthz",
                    env={},
                )
            )
            inference_env["BYES_SERVICE_SEG_HTTP_DOWNSTREAM"] = "reference"
        elif seg_mode == "sam3":
            start_specs.append(
                ServiceSpec(
                    name="sam3_seg",
                    module="services.sam3_seg_service.app:app",
                    port=int(ports["sam3"]),
                    health_path="/healthz",
                    env={
                        "BYES_SAM3_MODE": "fixture",
                    },
                )
            )
            inference_env["BYES_SERVICE_SEG_HTTP_DOWNSTREAM"] = "sam3"
        target_port = ports["sam3"] if seg_mode == "sam3" else ports["seg"]
        inference_env["BYES_SERVICE_SEG_PROVIDER"] = "http"
        inference_env["BYES_SERVICE_SEG_ENDPOINT"] = f"http://127.0.0.1:{int(target_port)}/seg"
        gateway_env["BYES_ENABLE_SEG"] = "1"
        gateway_env["BYES_SEG_BACKEND"] = "http"
        gateway_env["BYES_SEG_HTTP_URL"] = f"http://127.0.0.1:{int(ports['inference'])}/seg"

    if use_depth:
        depth_mode = services["depth"]
        if depth_mode == "reference":
            start_specs.append(
                ServiceSpec(
                    name="reference_depth",
                    module="services.reference_depth_service.app:app",
                    port=int(ports["depth"]),
                    health_path="/healthz",
                    env={},
                )
            )
            inference_env["BYES_SERVICE_DEPTH_HTTP_DOWNSTREAM"] = "reference"
            target_port = ports["depth"]
        else:
            start_specs.append(
                ServiceSpec(
                    name="da3_depth",
                    module="services.da3_depth_service.app:app",
                    port=int(ports["da3"]),
                    health_path="/healthz",
                    env={"BYES_DA3_MODE": "fixture"},
                )
            )
            inference_env["BYES_SERVICE_DEPTH_HTTP_DOWNSTREAM"] = "da3"
            target_port = ports["da3"]
        inference_env["BYES_SERVICE_DEPTH_PROVIDER"] = "http"
        inference_env["BYES_SERVICE_DEPTH_ENDPOINT"] = f"http://127.0.0.1:{int(target_port)}/depth"
        gateway_env["BYES_ENABLE_DEPTH"] = "1"
        gateway_env["BYES_DEPTH_BACKEND"] = "http"
        gateway_env["BYES_DEPTH_HTTP_URL"] = f"http://127.0.0.1:{int(ports['inference'])}/depth"

    if use_ocr:
        ocr_mode = services["ocr"]
        # currently only reference path is expected for OCR in this batch runner
        if ocr_mode != "reference":
            raise ValueError("services=ocr currently supports only reference")
        start_specs.append(
            ServiceSpec(
                name="reference_ocr",
                module="services.reference_ocr_service.app:app",
                port=int(ports["ocr"]),
                health_path="/healthz",
                env={},
            )
        )
        inference_env["BYES_SERVICE_OCR_PROVIDER"] = "http"
        inference_env["BYES_SERVICE_OCR_ENDPOINT"] = f"http://127.0.0.1:{int(ports['ocr'])}/ocr"
        gateway_env["BYES_ENABLE_OCR"] = "1"
        gateway_env["BYES_OCR_BACKEND"] = "http"
        gateway_env["BYES_OCR_HTTP_URL"] = f"http://127.0.0.1:{int(ports['inference'])}/ocr"

    if needs_inference:
        start_specs.append(
            ServiceSpec(
                name="inference",
                module="services.inference_service.app:app",
                port=int(ports["inference"]),
                health_path="/healthz",
                env=inference_env,
            )
        )

    # gateway is always needed in replay mode
    start_specs.append(
        ServiceSpec(
            name="gateway",
            module="main:app",
            port=int(ports["gateway"]),
            health_path="/openapi.json",
            env=gateway_env,
        )
    )
    return start_specs, gateway_env, inference_env


def _run_subprocess(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> tuple[int, str]:
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, check=False)  # noqa: S603
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if err:
        out = f"{out}\n{err}".strip()
    return int(result.returncode), out


def _run_report(*, target_run_package: Path, out_md: Path, out_json: Path, env: dict[str, str]) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(THIS_DIR / "report_run.py"),
        "--run-package",
        str(target_run_package),
        "--output",
        str(out_md),
        "--output-json",
        str(out_json),
    ]
    return _run_subprocess(cmd, cwd=REPO_ROOT, env=env)


def _run_replay(
    *,
    run_package: Path,
    replay_root: Path,
    base_url: str,
    ws_url: str,
    reset: bool,
    apply_scenario_calls: bool,
    env: dict[str, str],
) -> tuple[int, str, Path | None]:
    before = {p.resolve() for p in replay_root.iterdir()} if replay_root.exists() else set()
    replay_root.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(THIS_DIR / "replay_run_package.py"),
        "--run-package",
        str(run_package),
        "--base-url",
        base_url,
        "--ws-url",
        ws_url,
        "--out-dir",
        str(replay_root),
        "--interval-ms",
        "0",
    ]
    cmd.append("--reset" if reset else "--no-reset")
    cmd.append("--apply-scenario-calls" if apply_scenario_calls else "--skip-scenario-calls")
    code, out = _run_subprocess(cmd, cwd=REPO_ROOT, env=env)
    after = {p.resolve() for p in replay_root.iterdir()} if replay_root.exists() else set()
    created = sorted(list(after - before), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    latest = created[0] if created else None
    return code, out, latest


def run_dataset_benchmark(
    *,
    root: Path,
    out_dir: Path,
    glob_pattern: str,
    max_items: int,
    shuffle_items: bool,
    seed: int,
    replay: bool,
    reset: bool,
    apply_scenario_calls: bool,
    fail_on_drop: bool,
    ports: dict[str, int],
    services: dict[str, str],
    env_file: Path | None,
) -> tuple[dict[str, Any], int]:
    root = root.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    start_ms = _now_ms()

    packages = _discover_run_packages(root, glob_pattern=glob_pattern)
    if shuffle_items:
        rng = random.Random(seed)
        rng.shuffle(packages)
    if max_items > 0:
        packages = packages[:max_items]

    base_env = dict(os.environ)
    base_env["PYTHONUNBUFFERED"] = "1"
    base_env.update(_load_env_file(env_file))

    runtimes: list[ServiceRuntime] = []
    failures = 0
    try:
        if replay:
            specs, _gateway_env, _inference_env = _build_service_specs(ports=ports, services=services)
            logs_dir = out_dir / "service_logs"
            # Start non-gateway first, then gateway.
            specs_sorted = sorted(specs, key=lambda s: 1 if s.name == "gateway" else 0)
            for spec in specs_sorted:
                runtime = _start_service(spec, base_env=base_env, logs_dir=logs_dir)
                runtimes.append(runtime)

        for idx, package_dir in enumerate(packages, start=1):
            manifest = _manifest_for_run_package(package_dir)
            run_row: dict[str, Any] = {
                "index": idx,
                "runPackage": str(package_dir),
                "status": "ok",
                "error": None,
                "replayStdout": None,
                "reportStdout": None,
                "targetRunPackage": str(package_dir),
            }
            try:
                target_run_package = package_dir
                if replay:
                    if not _has_frames(package_dir, manifest):
                        run_row["status"] = "skipped_replay_no_frames"
                    else:
                        replay_root = out_dir / "replays"
                        code, stdout, replay_dir = _run_replay(
                            run_package=package_dir,
                            replay_root=replay_root,
                            base_url=f"http://127.0.0.1:{int(ports['gateway'])}",
                            ws_url=f"ws://127.0.0.1:{int(ports['gateway'])}/ws/events",
                            reset=reset,
                            apply_scenario_calls=apply_scenario_calls,
                            env=base_env,
                        )
                        run_row["replayStdout"] = stdout
                        if code != 0:
                            raise RuntimeError(f"replay failed (code={code})")
                        if replay_dir is not None and replay_dir.exists():
                            target_run_package = replay_dir
                            run_row["targetRunPackage"] = str(replay_dir)

                run_slug = _slug_from_path(package_dir, root)
                report_dir = out_dir / "reports"
                report_dir.mkdir(parents=True, exist_ok=True)
                report_md = report_dir / f"{run_slug}.md"
                report_json = report_dir / f"{run_slug}.json"
                rep_code, rep_stdout = _run_report(
                    target_run_package=target_run_package,
                    out_md=report_md,
                    out_json=report_json,
                    env=base_env,
                )
                run_row["reportStdout"] = rep_stdout
                if rep_code != 0:
                    raise RuntimeError(f"report failed (code={rep_code})")
                report_payload = json.loads(report_json.read_text(encoding="utf-8-sig"))
                run_row.update(_collect_summary_fields(run_package=target_run_package, manifest=_manifest_for_run_package(target_run_package), report=report_payload))
                run_row["reportPath"] = str(report_json)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                run_row["status"] = "error"
                run_row["error"] = str(exc)
            rows.append(run_row)
    finally:
        for runtime in reversed(runtimes):
            _stop_service(runtime)

    payload = {
        "schemaVersion": "byes.dataset_benchmark.v1",
        "generatedAtMs": _now_ms(),
        "durationMs": max(0, _now_ms() - start_ms),
        "root": str(root),
        "outDir": str(out_dir),
        "glob": glob_pattern,
        "replay": bool(replay),
        "discovered": len(packages),
        "processed": len(rows),
        "failures": int(failures),
        "rows": rows,
    }

    latest_json = out_dir / "latest.json"
    latest_csv = out_dir / "latest.csv"
    latest_md = out_dir / "latest.md"
    latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(latest_csv, rows)
    _write_markdown(latest_md, rows, payload)

    exit_code = 1 if (fail_on_drop and failures > 0) else 0
    return payload, exit_code


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch replay/report benchmark over run packages")
    parser.add_argument("--root", required=True, help="Root directory containing run packages")
    parser.add_argument(
        "--out",
        default=str(GATEWAY_ROOT / "artifacts" / "benchmarks" / f"v469_{_utc_compact()}"),
        help="Output directory (latest.json/latest.md/latest.csv)",
    )
    parser.add_argument("--glob", default="**/manifest.json", help="Glob pattern to discover manifests under --root")
    parser.add_argument("--max", type=int, default=50, help="Maximum run packages to process (<=0 means all)")
    parser.add_argument("--shuffle", type=int, default=1, help="Shuffle discovered run packages (1 or 0)")
    parser.add_argument("--seed", type=int, default=123, help="Seed for shuffle")
    parser.add_argument("--replay", type=int, default=1, help="Run replay step (1) or report-only (0)")
    parser.add_argument("--reset", type=int, default=1, help="Pass --reset to replay_run_package (1) or --no-reset (0)")
    parser.add_argument("--apply-scenario-calls", type=int, default=0, help="Apply scenario calls during replay (1/0)")
    parser.add_argument("--fail-on-drop", type=int, default=0, help="Exit non-zero on any run failure (1/0)")
    parser.add_argument(
        "--ports",
        default="gateway=19090,inference=19100,seg=19120,depth=19121,ocr=19122,sam3=19130,da3=19131",
        help="Port mapping string",
    )
    parser.add_argument(
        "--services",
        default="seg=reference,depth=reference,ocr=reference",
        help="Service backend map for replay mode (e.g. seg=reference,depth=reference,ocr=reference)",
    )
    parser.add_argument("--env-file", default="", help="Optional .env file with key=value overrides")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    payload, exit_code = run_dataset_benchmark(
        root=Path(args.root).resolve(),
        out_dir=Path(args.out).resolve(),
        glob_pattern=str(args.glob or "**/manifest.json"),
        max_items=int(args.max),
        shuffle_items=_parse_bool(args.shuffle),
        seed=int(args.seed),
        replay=_parse_bool(args.replay),
        reset=_parse_bool(args.reset),
        apply_scenario_calls=_parse_bool(args.apply_scenario_calls),
        fail_on_drop=_parse_bool(args.fail_on_drop),
        ports=_parse_ports(args.ports),
        services=_parse_services(args.services),
        env_file=Path(args.env_file).resolve() if str(args.env_file or "").strip() else None,
    )
    print(
        "[benchmark] discovered={d} processed={p} failures={f} replay={r}".format(
            d=payload.get("discovered", 0),
            p=payload.get("processed", 0),
            f=payload.get("failures", 0),
            r=payload.get("replay", False),
        )
    )
    print(f"[out] {Path(args.out).resolve() / 'latest.json'}")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
