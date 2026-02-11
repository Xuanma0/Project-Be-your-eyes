from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))

from byes.risk_calibration import DEFAULT_GRID, expand_grid, select_best_candidates  # noqa: E402


def _parse_bool(raw: str | bool) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid bool: {raw}")


def _parse_sizes(raw: str) -> list[int]:
    out: list[int] = []
    for item in str(raw or "").split(","):
        text = item.strip()
        if not text:
            continue
        value = int(text)
        if value <= 0:
            continue
        out.append(value)
    if not out:
        raise argparse.ArgumentTypeError("sizes is empty")
    return out


def _load_grid(raw: str | None) -> dict[str, list[float]]:
    if not raw:
        return dict(DEFAULT_GRID)
    text = str(raw).strip()
    if not text:
        return dict(DEFAULT_GRID)
    candidate = Path(text)
    payload_text = candidate.read_text(encoding="utf-8-sig") if candidate.exists() else text
    payload = json.loads(payload_text)
    if not isinstance(payload, dict):
        raise ValueError("grid json must be an object")
    normalized: dict[str, list[float]] = {}
    for key, value in payload.items():
        if not isinstance(value, list):
            continue
        normalized[str(key)] = [float(item) for item in value]
    return normalized or dict(DEFAULT_GRID)


def _load_manifest(path: Path) -> dict[str, Any]:
    for name in ("manifest.json", "run_manifest.json"):
        candidate = path / name
        if not candidate.exists():
            continue
        payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            return payload
    raise FileNotFoundError(f"manifest not found under {path}")


def _normalize_endpoint(url: str) -> str:
    text = str(url or "").strip()
    return text


def _check_risk_url_ready(risk_url: str) -> tuple[bool, str]:
    try:
        with httpx.Client(timeout=3.0) as client:
            probe = client.post(risk_url, json={"image_b64": "", "frameSeq": 1})
        if probe.status_code not in {200, 400, 422, 503}:
            return False, f"status={probe.status_code}"
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _load_frames(run_package: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    frames_meta_rel = str(manifest.get("framesMetaJsonl", "")).strip() or "frames_meta.jsonl"
    frames_meta = run_package / frames_meta_rel
    if not frames_meta.exists():
        raise FileNotFoundError(f"frames meta not found: {frames_meta}")

    rows: list[dict[str, Any]] = []
    with frames_meta.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                continue
            seq = int(payload.get("seq", 0) or payload.get("meta", {}).get("seq", 0) or 0)
            if seq <= 0:
                continue
            frame_rel = str(payload.get("framePath", "")).strip()
            if not frame_rel:
                frame_rel = f"frames/frame_{seq}.jpg"
            frame_path = run_package / frame_rel
            if not frame_path.exists():
                raise FileNotFoundError(f"frame missing for seq={seq}: {frame_path}")
            rows.append({"seq": seq, "framePath": frame_rel, "path": frame_path, "meta": payload.get("meta", {})})
    rows.sort(key=lambda item: int(item.get("seq", 0)))
    if not rows:
        raise ValueError("no frames found in run package")
    return rows


def _build_generated_run_package(
    source_run_package: Path,
    source_manifest: dict[str, Any],
    out_dir: Path,
    run_id: str,
) -> Path:
    package_dir = out_dir / run_id
    package_dir.mkdir(parents=True, exist_ok=True)

    # Copy frame + GT artifacts only.
    for rel in ("frames", "ground_truth"):
        src = source_run_package / rel
        if src.exists() and src.is_dir():
            shutil.copytree(src, package_dir / rel, dirs_exist_ok=True)
    for rel in ("frames_meta.jsonl",):
        src = source_run_package / rel
        if src.exists():
            shutil.copy2(src, package_dir / rel)

    metrics_before = package_dir / "metrics_before.txt"
    metrics_after = package_dir / "metrics_after.txt"
    metrics_before.write_text("byes_frame_received_total 0\n", encoding="utf-8")
    metrics_after.write_text("byes_frame_received_total 1\n", encoding="utf-8")

    manifest = dict(source_manifest)
    manifest["scenarioTag"] = run_id
    manifest["wsJsonl"] = "events/events_v1.jsonl"
    manifest["eventsV1Jsonl"] = "events/events_v1.jsonl"
    manifest["metricsBefore"] = "metrics_before.txt"
    manifest["metricsAfter"] = "metrics_after.txt"
    manifest["errors"] = []
    if not isinstance(manifest.get("groundTruth"), dict):
        manifest["groundTruth"] = {
            "version": 1,
            "riskJsonl": "ground_truth/depth_risk.jsonl",
            "matchWindowFrames": 1,
        }
    (package_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return package_dir


def _write_events_v1(
    *,
    run_package_dir: Path,
    frames: list[dict[str, Any]],
    risk_url: str,
    thresholds: dict[str, float],
    run_id: str,
) -> tuple[Path, list[str]]:
    events_dir = run_package_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    events_path = events_dir / "events_v1.jsonl"
    errors: list[str] = []
    endpoint = _normalize_endpoint(risk_url)

    with httpx.Client(timeout=10.0) as client, events_path.open("w", encoding="utf-8") as fp:
        for frame in frames:
            seq = int(frame.get("seq", 0) or 0)
            frame_path = Path(frame["path"])
            frame_bytes = frame_path.read_bytes()
            image_b64 = base64.b64encode(frame_bytes).decode("ascii")
            ts_ms = int(time.time() * 1000)
            payload = {
                "image_b64": image_b64,
                "frameSeq": seq,
                "riskThresholds": thresholds,
            }
            started = time.perf_counter()
            status = "ok"
            phase = "result"
            event_payload: dict[str, Any] = {
                "hazards": [],
                "backend": "http",
                "model": None,
                "endpoint": endpoint,
            }
            try:
                response = client.post(risk_url, json=payload)
                latency_ms = int((time.perf_counter() - started) * 1000)
                if response.status_code >= 400:
                    status = "error"
                    event_payload["error"] = f"http_{response.status_code}"
                    errors.append(f"seq={seq}: http_{response.status_code}")
                else:
                    body = response.json()
                    if isinstance(body, dict):
                        hazards = body.get("hazards")
                        if isinstance(hazards, list):
                            event_payload["hazards"] = [item for item in hazards if isinstance(item, dict)]
                        model = str(body.get("model", "")).strip()
                        if model:
                            event_payload["model"] = model
                        debug = body.get("debug")
                        if isinstance(debug, dict):
                            event_payload["debug"] = debug
            except Exception as exc:  # noqa: BLE001
                latency_ms = int((time.perf_counter() - started) * 1000)
                status = "error"
                event_payload["error"] = exc.__class__.__name__
                errors.append(f"seq={seq}: {exc.__class__.__name__}")

            event = {
                "schemaVersion": "byes.event.v1",
                "tsMs": ts_ms,
                "runId": run_id,
                "frameSeq": seq,
                "component": "gateway",
                "category": "tool",
                "name": "risk.hazards",
                "phase": phase,
                "status": status,
                "latencyMs": max(0, int(latency_ms)),
                "payload": event_payload,
            }
            fp.write(json.dumps(event, ensure_ascii=False) + "\n")
    return events_path, errors


def _run_report(run_package_dir: Path) -> tuple[bool, Path, str]:
    script = THIS_DIR / "report_run.py"
    out_json = run_package_dir / "report.json"
    out_md = run_package_dir / "report.md"
    cmd = [
        sys.executable,
        str(script),
        "--run-package",
        str(run_package_dir),
        "--output-json",
        str(out_json),
        "--output",
        str(out_md),
    ]
    result = subprocess.run(cmd, cwd=GATEWAY_ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = f"report failed rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}".strip()
        return False, out_json, detail
    return True, out_json, ""


def _extract_metrics(report_payload: dict[str, Any]) -> dict[str, Any]:
    quality = report_payload.get("quality", {}) if isinstance(report_payload, dict) else {}
    quality = quality if isinstance(quality, dict) else {}
    depth_risk = quality.get("depthRisk", {})
    depth_risk = depth_risk if isinstance(depth_risk, dict) else {}
    critical = depth_risk.get("critical", {})
    critical = critical if isinstance(critical, dict) else {}
    overall = depth_risk.get("overall", {})
    overall = overall if isinstance(overall, dict) else {}
    risk_latency = quality.get("riskLatencyMs", {})
    risk_latency = risk_latency if isinstance(risk_latency, dict) else {}
    return {
        "critical_fn": int(critical.get("missCriticalCount", 0) or 0),
        "fp_total": int(overall.get("fp", 0) or 0),
        "qualityScore": _to_float(quality.get("qualityScore")),
        "riskLatencyP90": int(risk_latency.get("p90", 0) or 0),
    }


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:  # noqa: BLE001
        return None


def _render_md(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Risk Threshold Calibration")
    lines.append("")
    lines.append("| rank | size | depthObsCrit | depthDropoffDelta | obsCrit | critical_fn | fp_total | qualityScore | riskLatencyP90 |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    topk = payload.get("topK", [])
    if not isinstance(topk, list):
        topk = []
    for idx, item in enumerate(topk, start=1):
        if not isinstance(item, dict):
            continue
        params = item.get("params", {}) if isinstance(item.get("params"), dict) else {}
        lines.append(
            "| {rank} | {size} | {depth_obs_crit} | {depth_dropoff_delta} | {obs_crit} | {critical_fn} | {fp_total} | {score} | {lat} |".format(
                rank=idx,
                size=item.get("size", ""),
                depth_obs_crit=params.get("depthObsCrit", ""),
                depth_dropoff_delta=params.get("depthDropoffDelta", ""),
                obs_crit=params.get("obsCrit", ""),
                critical_fn=item.get("critical_fn", ""),
                fp_total=item.get("fp_total", ""),
                score=item.get("qualityScore", ""),
                lat=item.get("riskLatencyP90", ""),
            )
        )
    lines.append("")
    lines.append(f"- bestParams: `{json.dumps(payload.get('bestParams', {}), ensure_ascii=False)}`")
    lines.append(f"- criticalFnGateSatisfied: `{payload.get('criticalFnGateSatisfied', True)}`")
    lines.append("- selectionRule: `critical_fn == 0 (if enabled) -> fp_total asc -> qualityScore desc -> riskLatencyP90 asc`")
    lines.append("- note: `--sizes` assumes inference_service is preconfigured to the tested depth input size.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibrate heuristic risk thresholds with a small grid search.")
    parser.add_argument(
        "--run-package",
        default=str(GATEWAY_ROOT / "tests" / "fixtures" / "run_package_risk_calib_10f"),
        help="run package path containing frames + GT",
    )
    parser.add_argument("--risk-url", default="http://127.0.0.1:19120/risk")
    parser.add_argument("--sizes", default="256")
    parser.add_argument("--grid", default="", help="grid json string or path")
    parser.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "byes_risk_calib" / "out.json"))
    parser.add_argument("--must-zero-critical-fn", type=_parse_bool, default=True)
    args = parser.parse_args(argv)

    run_package = Path(args.run_package)
    if not run_package.exists():
        print(f"run package not found: {run_package}")
        return 1

    ready, detail = _check_risk_url_ready(args.risk_url)
    if not ready:
        print("risk service not ready for calibration")
        print(f"- risk: {args.risk_url}")
        print(f"- detail: {detail}")
        return 1

    source_manifest = _load_manifest(run_package)
    source_frames = _load_frames(run_package, source_manifest)
    sizes = _parse_sizes(args.sizes)
    grid = _load_grid(args.grid)
    combinations = expand_grid(grid)

    out_json = Path(args.out)
    out_md = out_json.with_suffix(".md")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    run_root = out_json.parent / "runs"
    run_root.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for size in sizes:
        for combo_index, params in enumerate(combinations, start=1):
            run_id = f"calib_s{size}_g{combo_index:03d}"
            generated_pkg = _build_generated_run_package(run_package, source_manifest, run_root, run_id)
            events_path, call_errors = _write_events_v1(
                run_package_dir=generated_pkg,
                frames=source_frames,
                risk_url=args.risk_url,
                thresholds=params,
                run_id=run_id,
            )
            row: dict[str, Any] = {
                "size": int(size),
                "params": params,
                "critical_fn": 10**9,
                "fp_total": 10**9,
                "qualityScore": None,
                "riskLatencyP90": 10**9,
                "notes": "; ".join(call_errors),
                "eventsPath": str(events_path),
            }

            report_ok, report_json_path, report_error = _run_report(generated_pkg)
            if not report_ok:
                row["notes"] = "; ".join([row["notes"], report_error]).strip("; ")
                results.append(row)
                continue

            payload = json.loads(report_json_path.read_text(encoding="utf-8-sig"))
            row.update(_extract_metrics(payload))
            row["reportJson"] = str(report_json_path)
            row["runPackage"] = str(generated_pkg)
            results.append(row)

    best, topk = select_best_candidates(
        results,
        must_zero_critical_fn=bool(args.must_zero_critical_fn),
        top_k=5,
    )
    gate_satisfied = True
    if best is None and bool(args.must_zero_critical_fn):
        gate_satisfied = False
        best, topk = select_best_candidates(results, must_zero_critical_fn=False, top_k=5)
    summary = {
        "generatedAtMs": int(datetime.now(timezone.utc).timestamp() * 1000),
        "runPackage": str(run_package),
        "riskUrl": args.risk_url,
        "sizes": sizes,
        "grid": grid,
        "mustZeroCriticalFn": bool(args.must_zero_critical_fn),
        "criticalFnGateSatisfied": gate_satisfied,
        "bestParams": best.get("params", {}) if isinstance(best, dict) else {},
        "bestMetrics": {
            "critical_fn": int(best.get("critical_fn", 0) or 0) if isinstance(best, dict) else None,
            "fp_total": int(best.get("fp_total", 0) or 0) if isinstance(best, dict) else None,
            "qualityScore": _to_float(best.get("qualityScore")) if isinstance(best, dict) else None,
            "riskLatencyP90": int(best.get("riskLatencyP90", 0) or 0) if isinstance(best, dict) else None,
        },
        "topK": topk,
        "results": results,
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(_render_md(summary), encoding="utf-8")
    print(f"calibration json -> {out_json}")
    print(f"calibration md -> {out_md}")
    print(f"best params -> {json.dumps(summary['bestParams'], ensure_ascii=False)}")
    print(f"best metrics -> {json.dumps(summary['bestMetrics'], ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
