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

from byes.hazards.taxonomy_v1 import normalize_hazard_kind  # noqa: E402
from byes.risk_calibration import (  # noqa: E402
    DEFAULT_GRID,
    build_calibration_latency_metrics,
    expand_grid,
    load_jsonl,
    select_best_candidates,
)


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
            event_payload: dict[str, Any] = {
                "hazards": [],
                "backend": "http",
                "model": None,
                "endpoint": str(risk_url).strip(),
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
                "phase": "result",
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
    return {
        "critical_fn": int(critical.get("missCriticalCount", 0) or 0),
        "fp_total": int(overall.get("fp", 0) or 0),
        "qualityScore": _to_float(quality.get("qualityScore")),
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
    lines.append("> Latency is valid only when events_v1 contains non-zero `risk.hazards` `event.latencyMs` from real HTTP inference.")
    lines.append("")
    lines.append("| rank | size | depthObsCrit | depthDropoffDelta | obsCrit | critical_fn | fp_total | qualityScore | riskLatencyP90 | notes |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    topk = payload.get("topK", [])
    if not isinstance(topk, list):
        topk = []
    for idx, item in enumerate(topk, start=1):
        if not isinstance(item, dict):
            continue
        params = item.get("params", {}) if isinstance(item.get("params"), dict) else {}
        lines.append(
            "| {rank} | {size} | {depth_obs_crit} | {depth_dropoff_delta} | {obs_crit} | {critical_fn} | {fp_total} | {score} | {lat} | {notes} |".format(
                rank=idx,
                size=item.get("size", ""),
                depth_obs_crit=params.get("depthObsCrit", ""),
                depth_dropoff_delta=params.get("depthDropoffDelta", ""),
                obs_crit=params.get("obsCrit", ""),
                critical_fn=item.get("critical_fn", ""),
                fp_total=item.get("fp_total", ""),
                score=item.get("qualityScore", ""),
                lat=item.get("riskLatencyP90", ""),
                notes=str(item.get("notes", "")).replace("\n", " "),
            )
        )
    lines.append("")
    lines.append(f"- bestParams: `{json.dumps(payload.get('bestParams', {}), ensure_ascii=False)}`")
    lines.append(f"- criticalFnGateSatisfied: `{payload.get('criticalFnGateSatisfied', True)}`")
    lines.append("- selectionRule: `critical_fn == 0 (if enabled) -> fp_total asc -> qualityScore desc -> riskLatencyP90 asc`")
    lines.append("- note: `--sizes` assumes inference_service is preconfigured to the tested depth input size.")
    return "\n".join(lines) + "\n"


def _load_gt_hazards(run_package: Path, manifest: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    gt_cfg = manifest.get("groundTruth", {})
    risk_rel = ""
    if isinstance(gt_cfg, dict):
        risk_rel = str(gt_cfg.get("riskJsonl", "")).strip()
    if not risk_rel:
        risk_rel = "ground_truth/depth_risk.jsonl"
    risk_path = run_package / risk_rel
    rows: dict[int, list[dict[str, Any]]] = {}
    if not risk_path.exists():
        return rows
    with risk_path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                continue
            seq = int(item.get("frameSeq", item.get("seq", 0)) or 0)
            hazards_raw = item.get("hazards", [])
            hazards: list[dict[str, Any]] = []
            if isinstance(hazards_raw, list):
                for hazard in hazards_raw:
                    if not isinstance(hazard, dict):
                        continue
                    kind_raw = str(hazard.get("hazardKind", "")).strip()
                    kind_norm, _warn = normalize_hazard_kind(kind_raw)
                    if not kind_norm:
                        continue
                    severity = str(hazard.get("severity", "warning")).strip().lower() or "warning"
                    hazards.append({"hazardKind": kind_norm, "severity": severity, "rawHazardKind": kind_raw})
            rows[seq] = hazards
    return rows


def _collect_prediction_evidence(events_rows: list[dict[str, Any]]) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    pred_map: dict[int, dict[str, Any]] = {}
    debug_map: dict[int, dict[str, Any]] = {}
    for row in events_rows:
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if not isinstance(event, dict):
            continue
        if str(event.get("category", "")).strip().lower() != "tool":
            continue
        if str(event.get("name", "")).strip().lower() != "risk.hazards":
            continue
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue
        seq = int(event.get("frameSeq", 0) or 0)
        if seq <= 0:
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        hazards_rows = payload.get("hazards")
        normalized_kinds: list[str] = []
        raw_kinds: list[str] = []
        if isinstance(hazards_rows, list):
            for hazard in hazards_rows:
                if not isinstance(hazard, dict):
                    continue
                raw = str(hazard.get("hazardKind", "")).strip()
                if not raw:
                    continue
                raw_kinds.append(raw)
                normalized, _warn = normalize_hazard_kind(raw)
                if normalized:
                    normalized_kinds.append(normalized)
        pred_map[seq] = {"rawKinds": raw_kinds, "kinds": normalized_kinds}
        debug_payload = payload.get("debug")
        if isinstance(debug_payload, dict):
            debug_map[seq] = debug_payload
    return pred_map, debug_map


def _classify_miss_reason(
    *,
    gt_kind: str,
    predicted_norm_kinds: list[str],
    predicted_raw_kinds: list[str],
    thresholds: dict[str, Any],
    depth_evidence: dict[str, Any],
) -> str:
    if not predicted_norm_kinds:
        return "A) no_prediction_in_window"

    if any(_normalize_kind(raw) == gt_kind and str(raw).strip().lower() != gt_kind for raw in predicted_raw_kinds):
        return "D) eval_mismatch(alias/normalization)"

    if gt_kind == "dropoff":
        delta = _to_float(depth_evidence.get("dropoffDelta"))
        threshold = _to_float(thresholds.get("depthDropoffDelta"))
        if delta is not None and threshold is not None and delta > 0 and delta < threshold:
            return "C) predicted_but_below_threshold"
    if gt_kind == "obstacle_close":
        p10 = _to_float(depth_evidence.get("depthP10"))
        threshold = _to_float(thresholds.get("depthObsCrit"))
        if p10 is not None and threshold is not None and p10 > threshold:
            return "C) predicted_but_below_threshold"

    if gt_kind not in predicted_norm_kinds:
        return "B) predicted_other_kind"
    return "D) eval_mismatch(alias/normalization)"


def _normalize_kind(kind: str) -> str:
    normalized, _warnings = normalize_hazard_kind(str(kind))
    return normalized


def _build_fn_report(
    *,
    candidate: dict[str, Any],
    source_manifest: dict[str, Any],
    source_run_package: Path,
) -> dict[str, Any]:
    report_json_path = Path(str(candidate.get("reportJson", "")).strip())
    events_path = Path(str(candidate.get("eventsPath", "")).strip())
    if not report_json_path.exists() or not events_path.exists():
        return {"misses": [], "note": "reportJson or eventsPath missing"}

    report_payload = json.loads(report_json_path.read_text(encoding="utf-8-sig"))
    quality = report_payload.get("quality", {}) if isinstance(report_payload, dict) else {}
    quality = quality if isinstance(quality, dict) else {}
    depth_risk = quality.get("depthRisk", {})
    depth_risk = depth_risk if isinstance(depth_risk, dict) else {}
    top_misses = depth_risk.get("topMisses", [])
    if not isinstance(top_misses, list):
        top_misses = []
    window_default = int(depth_risk.get("matchWindowFrames", 1) or 1)

    gt_map = _load_gt_hazards(source_run_package, source_manifest)
    events_rows = load_jsonl(events_path)
    pred_map, debug_map = _collect_prediction_evidence(events_rows)

    misses: list[dict[str, Any]] = []
    for miss in top_misses:
        if not isinstance(miss, dict):
            continue
        frame_seq = int(miss.get("frameSeq", 0) or 0)
        if frame_seq <= 0:
            continue
        gt_kind = str(miss.get("hazardKind", "")).strip().lower()
        severity = str(miss.get("severity", "")).strip().lower() or None
        if not gt_kind or not severity:
            gt_rows = gt_map.get(frame_seq, [])
            critical_rows = [row for row in gt_rows if str(row.get("severity", "")).strip().lower() == "critical"]
            chosen = critical_rows[0] if critical_rows else (gt_rows[0] if gt_rows else {})
            if isinstance(chosen, dict):
                if not gt_kind:
                    gt_kind = str(chosen.get("hazardKind", "")).strip().lower()
                if not severity:
                    severity = str(chosen.get("severity", "")).strip().lower() or None
        if severity != "critical":
            continue
        window = int(miss.get("window", window_default) or window_default)

        preds_window: list[dict[str, Any]] = []
        pred_norm_kinds: list[str] = []
        pred_raw_kinds: list[str] = []
        nearest_debug: dict[str, Any] | None = debug_map.get(frame_seq)
        nearest_gap = 10**9
        for seq, preds in sorted(pred_map.items(), key=lambda item: int(item[0])):
            gap = abs(int(seq) - frame_seq)
            if gap > window:
                continue
            kinds = list(preds.get("kinds", []))
            raw_kinds = list(preds.get("rawKinds", []))
            preds_window.append({"frameSeq": int(seq), "hazardKinds": kinds, "rawHazardKinds": raw_kinds})
            pred_norm_kinds.extend(kinds)
            pred_raw_kinds.extend(raw_kinds)
            if gap < nearest_gap and seq in debug_map:
                nearest_gap = gap
                nearest_debug = debug_map.get(seq)

        debug_thresholds = {}
        debug_depth = {}
        debug_visual = {}
        if isinstance(nearest_debug, dict):
            thresholds = nearest_debug.get("thresholds")
            depth_node = nearest_debug.get("depth")
            visual_node = nearest_debug.get("visual")
            debug_thresholds = thresholds if isinstance(thresholds, dict) else {}
            debug_depth = depth_node if isinstance(depth_node, dict) else {}
            debug_visual = visual_node if isinstance(visual_node, dict) else {}

        roi_stats = debug_depth.get("roiStats", {}) if isinstance(debug_depth, dict) else {}
        if not isinstance(roi_stats, dict):
            roi_stats = {}
        depth_evidence = {
            "depthMin": roi_stats.get("depthMin"),
            "depthP10": roi_stats.get("depthP10"),
            "dropoffDelta": roi_stats.get("dropoffDelta"),
            "near": roi_stats.get("depthNearMedian"),
            "far": roi_stats.get("depthFarMedian"),
        }
        visual_evidence = {
            "dropoffSignal": debug_visual.get("dropoffSignal"),
            "contrastSignal": debug_visual.get("contrastSignal"),
            "edgeDensityBottom": debug_visual.get("edgeDensityBottom"),
        }
        thresholds_view = dict(debug_thresholds) if debug_thresholds else dict(candidate.get("params", {}))
        reason = _classify_miss_reason(
            gt_kind=gt_kind,
            predicted_norm_kinds=pred_norm_kinds,
            predicted_raw_kinds=pred_raw_kinds,
            thresholds=thresholds_view,
            depth_evidence=depth_evidence,
        )
        misses.append(
            {
                "frameSeq": frame_seq,
                "gtHazardKind": gt_kind,
                "gtSeverity": severity,
                "predictedInWindow": preds_window,
                "thresholds": thresholds_view,
                "depthEvidence": depth_evidence,
                "visualEvidence": visual_evidence,
                "reason": reason,
            }
        )

    return {
        "runPackage": str(source_run_package),
        "candidateRunPackage": candidate.get("runPackage"),
        "bestParams": candidate.get("params", {}),
        "bestMetrics": {
            "critical_fn": candidate.get("critical_fn"),
            "fp_total": candidate.get("fp_total"),
            "qualityScore": candidate.get("qualityScore"),
            "riskLatencyP90": candidate.get("riskLatencyP90"),
        },
        "missCount": len(misses),
        "misses": misses,
    }


def _render_fn_report_md(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Calibration FN Report")
    lines.append("")
    lines.append(f"- missCount: `{payload.get('missCount', 0)}`")
    lines.append(f"- bestParams: `{json.dumps(payload.get('bestParams', {}), ensure_ascii=False)}`")
    lines.append(f"- bestMetrics: `{json.dumps(payload.get('bestMetrics', {}), ensure_ascii=False)}`")
    lines.append("")
    lines.append("| frameSeq | gt | predictedInWindow | reason | depthP10 | depthMin | dropoffDelta |")
    lines.append("|---:|---|---|---|---:|---:|---:|")
    misses = payload.get("misses", [])
    if not isinstance(misses, list):
        misses = []
    for miss in misses:
        if not isinstance(miss, dict):
            continue
        depth = miss.get("depthEvidence", {}) if isinstance(miss.get("depthEvidence"), dict) else {}
        preds = miss.get("predictedInWindow", [])
        preds_text = json.dumps(preds, ensure_ascii=False)
        lines.append(
            "| {seq} | {kind}/{sev} | {pred} | {reason} | {p10} | {minv} | {delta} |".format(
                seq=miss.get("frameSeq"),
                kind=miss.get("gtHazardKind", ""),
                sev=miss.get("gtSeverity", ""),
                pred=preds_text.replace("|", "/"),
                reason=miss.get("reason", ""),
                p10=depth.get("depthP10"),
                minv=depth.get("depthMin"),
                delta=depth.get("dropoffDelta"),
            )
        )
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
            events_rows = load_jsonl(events_path)
            latency_metrics = build_calibration_latency_metrics(events_rows)
            latency_info = latency_metrics.get("riskLatency", {})
            notes: list[str] = [item for item in call_errors if item]
            if isinstance(latency_metrics.get("notes"), list):
                notes.extend(str(item) for item in latency_metrics["notes"] if str(item).strip())
            risk_latency_p90: int | None = latency_metrics.get("riskLatencyP90")

            row: dict[str, Any] = {
                "size": int(size),
                "params": params,
                "critical_fn": 10**9,
                "fp_total": 10**9,
                "qualityScore": None,
                "riskLatencyP90": risk_latency_p90,
                "riskLatency": latency_info,
                "notes": "; ".join(notes),
                "eventsPath": str(events_path),
                "riskLatencyRawCount": int(latency_metrics.get("riskLatencyRawCount", 0) or 0),
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

    best_zero, topk_zero = select_best_candidates(
        results,
        must_zero_critical_fn=bool(args.must_zero_critical_fn),
        top_k=5,
    )
    gate_satisfied = True
    best = best_zero
    topk = topk_zero
    if best_zero is None and bool(args.must_zero_critical_fn):
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
            "riskLatencyP90": best.get("riskLatencyP90") if isinstance(best, dict) else None,
        },
        "topK": topk,
        "results": results,
    }

    if not gate_satisfied and isinstance(best, dict):
        fn_report_payload = _build_fn_report(candidate=best, source_manifest=source_manifest, source_run_package=run_package)
        fn_json = out_json.parent / "fn_report.json"
        fn_md = out_json.parent / "fn_report.md"
        fn_json.write_text(json.dumps(fn_report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        fn_md.write_text(_render_fn_report_md(fn_report_payload), encoding="utf-8")
        summary["fnReportJson"] = str(fn_json)
        summary["fnReportMd"] = str(fn_md)

    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(_render_md(summary), encoding="utf-8")
    print(f"calibration json -> {out_json}")
    print(f"calibration md -> {out_md}")
    if "fnReportJson" in summary:
        print(f"fn report json -> {summary['fnReportJson']}")
        print(f"fn report md -> {summary.get('fnReportMd', '')}")
    print(f"best params -> {json.dumps(summary['bestParams'], ensure_ascii=False)}")
    print(f"best metrics -> {json.dumps(summary['bestMetrics'], ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
