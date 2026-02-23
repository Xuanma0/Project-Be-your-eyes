from __future__ import annotations

import argparse
import csv
import json
import os
import random
import statistics
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


@dataclass
class BenchmarkProfile:
    name: str
    services: dict[str, str]
    env: dict[str, str]
    prehooks: list[dict[str, Any]]


METRIC_FIELDS = [
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
    "slam_coverage",
    "slam_align_residual_p90",
    "slam_ate_rmse",
    "slam_rpe_trans_rmse",
    "costmap_coverage",
    "costmap_latency_p90",
    "costmap_fused_coverage",
    "costmap_fused_latency_p90",
    "costmap_fused_iou_p90",
    "costmap_fused_flicker_rate_mean",
    "costmap_fused_shift_used_rate",
    "costmap_fused_shift_gate_reject_rate",
    "plan_costmap_ctx_used_rate",
    "plan_score",
    "plan_fallback_used",
]


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


def _sanitize_services(raw: dict[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for key in ("seg", "depth", "ocr"):
        value = str(raw.get(key, "")).strip().lower()
        if value in {"reference", "sam3", "da3"}:
            out[key] = value
    return out


def _sanitize_prehooks(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        hook_type = str(item.get("type", "")).strip().lower()
        if not hook_type:
            continue
        if hook_type == "pyslam_run":
            mode = str(item.get("mode", "fixture")).strip().lower() or "fixture"
            if mode not in {"fixture", "wsl"}:
                mode = "fixture"
            tum_glob = str(item.get("tumGlob", "pyslam/*.txt")).strip() or "pyslam/*.txt"
            align_mode = str(item.get("alignMode", "auto")).strip().lower() or "auto"
            then_ingest = _parse_bool(item.get("thenIngest", True))
            replace_existing = _parse_bool(item.get("replaceExisting", True))
            save_online = _parse_bool(item.get("saveOnline", True))
            save_final = _parse_bool(item.get("saveFinal", True))
            out.append(
                {
                    "type": "pyslam_run",
                    "mode": mode,
                    "thenIngest": bool(then_ingest),
                    "tumGlob": tum_glob,
                    "alignMode": align_mode,
                    "replaceExisting": bool(replace_existing),
                    "wslDistro": str(item.get("wslDistro", "Ubuntu")).strip() or "Ubuntu",
                    "pyslamRoot": str(item.get("pyslamRoot", "")).strip(),
                    "config": str(item.get("config", "")).strip(),
                    "saveOnline": bool(save_online),
                    "saveFinal": bool(save_final),
                }
            )
            continue
        if hook_type != "pyslam_ingest":
            out.append({"type": hook_type})
            continue
        tum_glob = str(item.get("tumGlob", "pyslam/*.txt")).strip() or "pyslam/*.txt"
        align_mode = str(item.get("alignMode", "auto")).strip().lower() or "auto"
        replace_existing = _parse_bool(item.get("replaceExisting", False))
        out.append(
            {
                "type": "pyslam_ingest",
                "tumGlob": tum_glob,
                "alignMode": align_mode,
                "replaceExisting": bool(replace_existing),
            }
        )
    return out


def _services_compact(services: dict[str, str]) -> str:
    if not services:
        return ""
    parts: list[str] = []
    for key in ("seg", "depth", "ocr"):
        if key in services:
            parts.append(f"{key}={services[key]}")
    return ",".join(parts)


def _services_with_prehooks(services: dict[str, str], prehooks: list[dict[str, Any]]) -> str:
    base = _services_compact(services)
    has_pyslam_run = any(
        isinstance(hook, dict) and str(hook.get("type", "")).strip().lower() == "pyslam_run"
        for hook in prehooks
    )
    if has_pyslam_run:
        return f"{base}+pyslam_run" if base else "pyslam_run"
    return base


def _load_profiles(path: Path) -> list[BenchmarkProfile]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"profiles file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("profiles file must be a JSON object with key: profiles")
    profiles_raw = payload.get("profiles")
    if not isinstance(profiles_raw, list):
        raise ValueError("profiles file missing array: profiles")

    profiles: list[BenchmarkProfile] = []
    seen_names: set[str] = set()
    for idx, item in enumerate(profiles_raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"profiles[{idx}] must be an object")
        name = str(item.get("name", "")).strip()
        if not name:
            raise ValueError(f"profiles[{idx}] missing non-empty name")
        if name in seen_names:
            raise ValueError(f"duplicate profile name: {name}")
        seen_names.add(name)

        services = _sanitize_services(item.get("services"))
        env_raw = item.get("env")
        env: dict[str, str] = {}
        if isinstance(env_raw, dict):
            env = {str(k): str(v) for k, v in env_raw.items()}
        prehooks = _sanitize_prehooks(item.get("prehooks"))
        profiles.append(BenchmarkProfile(name=name, services=services, env=env, prehooks=prehooks))
    if not profiles:
        raise ValueError("profiles array is empty")
    return profiles


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = int(max(0, min(len(ordered) - 1, round((len(ordered) - 1) * q))))
    return float(ordered[idx])


def _to_metric_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except Exception:
        return None


def _metric_stats(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values: list[float] = []
    for row in rows:
        v = _to_metric_number(row.get(field))
        if v is not None:
            values.append(v)
    if not values:
        return {"count": 0, "mean": None, "median": None, "p90": None}
    return {
        "count": len(values),
        "mean": float(statistics.fmean(values)),
        "median": float(statistics.median(values)),
        "p90": _quantile(values, 0.90),
    }


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
    costmap = quality.get("costmap")
    costmap = costmap if isinstance(costmap, dict) else {}
    costmap_fused = quality.get("costmapFused")
    costmap_fused = costmap_fused if isinstance(costmap_fused, dict) else {}
    slam_error = quality.get("slamError")
    slam_error = slam_error if isinstance(slam_error, dict) else {}
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
    plan_context = report.get("planContext")
    plan_context = plan_context if isinstance(plan_context, dict) else {}
    plan_context_costmap = plan_context.get("costmap")
    plan_context_costmap = plan_context_costmap if isinstance(plan_context_costmap, dict) else {}
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
        "slam_coverage": _to_float(slam.get("coverage")),
        "slam_align_residual_p90": _to_int(_nested_get(slam, ["alignment", "residualMs", "p90"])),
        "slam_ate_rmse": _to_float(slam_error.get("ate_rmse_m")),
        "slam_rpe_trans_rmse": _to_float(slam_error.get("rpe_trans_rmse_m")),
        "costmap_coverage": _to_float(costmap.get("coverage")),
        "costmap_latency_p90": _to_int(_nested_get(costmap, ["latencyMs", "p90"])),
        "costmap_fused_coverage": _to_float(costmap_fused.get("coverage")),
        "costmap_fused_latency_p90": _to_int(_nested_get(costmap_fused, ["latencyMs", "p90"])),
        "costmap_fused_iou_p90": _to_float(_nested_get(costmap_fused, ["stability", "iouPrevP90"])),
        "costmap_fused_flicker_rate_mean": _to_float(_nested_get(costmap_fused, ["stability", "flickerRatePrevMean"])),
        "costmap_fused_shift_used_rate": _to_float(costmap_fused.get("shiftUsedRate")),
        "costmap_fused_shift_gate_reject_rate": _to_float(costmap_fused.get("shiftGateRejectRate")),
        "slam_model_preferred": str(costmap_fused.get("slamModelPreferred", "")).strip() or None,
        "plan_costmap_ctx_used_rate": _to_float(plan_context_costmap.get("contextUsedRate")),
        "plan_score": _to_float(plan_quality.get("score")),
        "plan_fallback_used": bool(plan_quality.get("fallbackUsed")) if "fallbackUsed" in plan_quality else None,
    }


def _summary_to_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    out = {
        "profile": row.get("profile"),
        "services": row.get("services"),
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
        "slam_coverage": row.get("slam_coverage"),
        "slam_align_residual_p90": row.get("slam_align_residual_p90"),
        "slam_ate_rmse": row.get("slam_ate_rmse"),
        "slam_rpe_trans_rmse": row.get("slam_rpe_trans_rmse"),
        "costmap_coverage": row.get("costmap_coverage"),
        "costmap_latency_p90": row.get("costmap_latency_p90"),
        "costmap_fused_coverage": row.get("costmap_fused_coverage"),
        "costmap_fused_latency_p90": row.get("costmap_fused_latency_p90"),
        "costmap_fused_iou_p90": row.get("costmap_fused_iou_p90"),
        "costmap_fused_flicker_rate_mean": row.get("costmap_fused_flicker_rate_mean"),
        "costmap_fused_shift_used_rate": row.get("costmap_fused_shift_used_rate"),
        "costmap_fused_shift_gate_reject_rate": row.get("costmap_fused_shift_gate_reject_rate"),
        "slam_model_preferred": row.get("slam_model_preferred"),
        "plan_costmap_ctx_used_rate": row.get("plan_costmap_ctx_used_rate"),
        "plan_score": row.get("plan_score"),
        "plan_fallback_used": row.get("plan_fallback_used"),
        "status": row.get("status"),
        "error": row.get("error"),
    }
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "profile",
        "services",
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
        "slam_coverage",
        "slam_align_residual_p90",
        "slam_ate_rmse",
        "slam_rpe_trans_rmse",
        "costmap_coverage",
        "costmap_latency_p90",
        "costmap_fused_coverage",
        "costmap_fused_latency_p90",
        "costmap_fused_iou_p90",
        "costmap_fused_flicker_rate_mean",
        "costmap_fused_shift_used_rate",
        "costmap_fused_shift_gate_reject_rate",
        "slam_model_preferred",
        "plan_costmap_ctx_used_rate",
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
    lines.append(
        "| profile | runId | frames | qualityScore | critical_fn | riskP90 | e2eP90 | ttsP90 | arP90 | segF1 | depthAbsRel | ocrCER | slamTrack | slamCoverage | slamAlignP90 | slamATE | slamRPE | costmapCoverage | costmapP90 | costmapFusedCoverage | costmapFusedIoUP90 | costmapFusedFlickerMean | costmapFusedShiftUsedRate | costmapFusedShiftRejectRate | slamModelPreferred | planCostmapUsed | status |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for row in rows:
        lines.append(
            "| {profile} | {run_id} | {frames} | {quality} | {critical_fn} | {risk} | {e2e} | {tts} | {ar} | {seg} | {depth} | {ocr} | {slam} | {slam_cov} | {slam_align} | {slam_ate} | {slam_rpe} | {costmap_cov} | {costmap_p90} | {costmap_fused_cov} | {costmap_fused_iou} | {costmap_fused_flicker} | {costmap_fused_shift_used} | {costmap_fused_shift_reject} | {slam_model_preferred} | {plan_costmap_used} | {status} |".format(
                profile=row.get("profile"),
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
                slam_cov=row.get("slam_coverage"),
                slam_align=row.get("slam_align_residual_p90"),
                slam_ate=row.get("slam_ate_rmse"),
                slam_rpe=row.get("slam_rpe_trans_rmse"),
                costmap_cov=row.get("costmap_coverage"),
                costmap_p90=row.get("costmap_latency_p90"),
                costmap_fused_cov=row.get("costmap_fused_coverage"),
                costmap_fused_iou=row.get("costmap_fused_iou_p90"),
                costmap_fused_flicker=row.get("costmap_fused_flicker_rate_mean"),
                costmap_fused_shift_used=row.get("costmap_fused_shift_used_rate"),
                costmap_fused_shift_reject=row.get("costmap_fused_shift_gate_reject_rate"),
                slam_model_preferred=row.get("slam_model_preferred"),
                plan_costmap_used=row.get("plan_costmap_ctx_used_rate"),
                status=row.get("status"),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_latest_bundle(*, out_dir: Path, payload: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    latest_json = out_dir / "latest.json"
    latest_csv = out_dir / "latest.csv"
    latest_md = out_dir / "latest.md"
    latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(latest_csv, rows)
    _write_markdown(latest_md, rows, payload)


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


def _run_pyslam_ingest_prehook(
    *,
    source_run_package: Path,
    target_run_package: Path,
    hook: dict[str, Any],
    env: dict[str, str],
) -> tuple[list[str], list[str], str | None]:
    warnings: list[str] = []
    errors: list[str] = []
    tum_glob = str(hook.get("tumGlob", "pyslam/*.txt")).strip() or "pyslam/*.txt"
    align_mode = str(hook.get("alignMode", "auto")).strip().lower() or "auto"
    replace_existing = bool(hook.get("replaceExisting", False))

    tum_files = sorted(path for path in source_run_package.glob(tum_glob) if path.is_file())
    if not tum_files and source_run_package.resolve() != target_run_package.resolve():
        tum_files = sorted(path for path in target_run_package.glob(tum_glob) if path.is_file())
    if not tum_files:
        warnings.append(f"pyslam_ingest: no trajectory matched tumGlob='{tum_glob}'")
        return warnings, errors, None

    cmd = [
        sys.executable,
        str(THIS_DIR / "ingest_pyslam_tum.py"),
        "--run-package",
        str(target_run_package),
        "--traj-label",
        "auto",
        "--align-mode",
        align_mode,
        "--replace-existing",
        "1" if replace_existing else "0",
    ]
    for tum_file in tum_files:
        cmd.extend(["--tum", str(tum_file)])
    code, out = _run_subprocess(cmd, cwd=REPO_ROOT, env=env)
    if code != 0:
        errors.append(f"pyslam_ingest failed (code={code})")
    return warnings, errors, out


def _run_pyslam_run_prehook(
    *,
    target_run_package: Path,
    hook: dict[str, Any],
    env: dict[str, str],
) -> tuple[list[str], list[str], str | None]:
    warnings: list[str] = []
    errors: list[str] = []
    mode = str(hook.get("mode", "fixture")).strip().lower() or "fixture"
    wsl_distro = str(hook.get("wslDistro", "Ubuntu")).strip() or "Ubuntu"
    pyslam_root = str(hook.get("pyslamRoot", "")).strip()
    config = str(hook.get("config", "")).strip()
    save_online = bool(hook.get("saveOnline", True))
    save_final = bool(hook.get("saveFinal", True))

    cmd = [
        sys.executable,
        str(THIS_DIR / "run_pyslam_on_run_package.py"),
        "--run-package",
        str(target_run_package),
        "--mode",
        mode,
        "--wsl-distro",
        wsl_distro,
        "--save-online",
        "1" if save_online else "0",
        "--save-final",
        "1" if save_final else "0",
    ]
    if pyslam_root:
        cmd.extend(["--pyslam-root", pyslam_root])
    if config:
        cmd.extend(["--config", config])
    code, out = _run_subprocess(cmd, cwd=REPO_ROOT, env=env)
    if code != 0:
        errors.append(f"pyslam_run failed (code={code})")
    return warnings, errors, out


def _apply_prehooks(
    *,
    source_run_package: Path,
    target_run_package: Path,
    prehooks: list[dict[str, Any]],
    env: dict[str, str],
) -> tuple[list[str], list[str], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    applied: list[dict[str, Any]] = []
    outputs: list[str] = []
    for hook in prehooks:
        if not isinstance(hook, dict):
            continue
        hook_type = str(hook.get("type", "")).strip().lower()
        if not hook_type:
            continue
        hook_entry: dict[str, Any] = {"type": hook_type}
        if hook_type == "pyslam_ingest":
            hook_warnings, hook_errors, hook_out = _run_pyslam_ingest_prehook(
                source_run_package=source_run_package,
                target_run_package=target_run_package,
                hook=hook,
                env=env,
            )
            warnings.extend(hook_warnings)
            errors.extend(hook_errors)
            if hook_out:
                outputs.append(hook_out)
            hook_entry["tumGlob"] = str(hook.get("tumGlob", "pyslam/*.txt"))
            hook_entry["alignMode"] = str(hook.get("alignMode", "auto"))
            hook_entry["replaceExisting"] = bool(hook.get("replaceExisting", False))
            hook_entry["warnings"] = hook_warnings
            hook_entry["errors"] = hook_errors
        elif hook_type == "pyslam_run":
            hook_warnings, hook_errors, hook_out = _run_pyslam_run_prehook(
                target_run_package=target_run_package,
                hook=hook,
                env=env,
            )
            warnings.extend(hook_warnings)
            errors.extend(hook_errors)
            if hook_out:
                outputs.append(hook_out)
            hook_entry["mode"] = str(hook.get("mode", "fixture"))
            hook_entry["thenIngest"] = bool(hook.get("thenIngest", True))
            hook_entry["tumGlob"] = str(hook.get("tumGlob", "pyslam/*.txt"))
            hook_entry["alignMode"] = str(hook.get("alignMode", "auto"))
            hook_entry["replaceExisting"] = bool(hook.get("replaceExisting", True))
            hook_entry["warnings"] = list(hook_warnings)
            hook_entry["errors"] = list(hook_errors)
            if not hook_errors and bool(hook.get("thenIngest", True)):
                ingest_hook = {
                    "type": "pyslam_ingest",
                    "tumGlob": str(hook.get("tumGlob", "pyslam/*.txt")),
                    "alignMode": str(hook.get("alignMode", "auto")),
                    "replaceExisting": bool(hook.get("replaceExisting", True)),
                }
                ingest_warnings, ingest_errors, ingest_out = _run_pyslam_ingest_prehook(
                    source_run_package=source_run_package,
                    target_run_package=target_run_package,
                    hook=ingest_hook,
                    env=env,
                )
                warnings.extend(ingest_warnings)
                errors.extend(ingest_errors)
                hook_entry["warnings"].extend(ingest_warnings)
                hook_entry["errors"].extend(ingest_errors)
                if ingest_out:
                    outputs.append(ingest_out)
        else:
            warning = f"unknown prehook type '{hook_type}', skipped"
            warnings.append(warning)
            hook_entry["warnings"] = [warning]
        applied.append(hook_entry)
    return warnings, errors, applied, outputs


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
    profile_name: str = "default",
    env_overrides: dict[str, str] | None = None,
    prehooks: list[dict[str, Any]] | None = None,
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
    if env_overrides:
        base_env.update({str(k): str(v) for k, v in env_overrides.items()})
    active_prehooks = list(prehooks or [])
    services_compact = _services_with_prehooks(services, active_prehooks)

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
                "profile": profile_name,
                "services": services_compact,
                "runPackage": str(package_dir),
                "status": "ok",
                "error": None,
                "replayStdout": None,
                "reportStdout": None,
                "prehookStdout": [],
                "prehookWarnings": [],
                "prehookErrors": [],
                "prehooksApplied": [],
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

                if active_prehooks:
                    hook_warnings, hook_errors, hook_entries, hook_outputs = _apply_prehooks(
                        source_run_package=package_dir,
                        target_run_package=target_run_package,
                        prehooks=active_prehooks,
                        env=base_env,
                    )
                    run_row["prehooksApplied"] = hook_entries
                    run_row["prehookWarnings"] = hook_warnings
                    run_row["prehookErrors"] = hook_errors
                    run_row["prehookStdout"] = hook_outputs
                    if hook_errors:
                        raise RuntimeError("; ".join(hook_errors))

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
        "profile": profile_name,
        "services": services_compact,
        "prehooks": active_prehooks,
        "root": str(root),
        "outDir": str(out_dir),
        "glob": glob_pattern,
        "replay": bool(replay),
        "discovered": len(packages),
        "processed": len(rows),
        "failures": int(failures),
        "rows": rows,
    }

    _write_latest_bundle(out_dir=out_dir, payload=payload, rows=rows)

    exit_code = 1 if (fail_on_drop and failures > 0) else 0
    return payload, exit_code


def _summarize_profile_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    ok_rows = [row for row in rows if str(row.get("status", "")).strip().lower() != "error"]
    return {field: _metric_stats(ok_rows, field) for field in METRIC_FIELDS}


def _build_matrix_summary_payload(
    *,
    root: Path,
    out_dir: Path,
    replay: bool,
    profile_payloads: list[dict[str, Any]],
    generated_at_ms: int,
) -> dict[str, Any]:
    profile_summaries: list[dict[str, Any]] = []
    combined_rows: list[dict[str, Any]] = []
    for payload in profile_payloads:
        rows = payload.get("rows")
        rows = rows if isinstance(rows, list) else []
        combined_rows.extend(rows)
        mode_counter: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            mode_text = str(row.get("slam_model_preferred", "")).strip()
            if mode_text:
                mode_counter[mode_text] = mode_counter.get(mode_text, 0) + 1
        slam_model_preferred_mode = None
        if mode_counter:
            slam_model_preferred_mode = sorted(mode_counter.items(), key=lambda item: (-item[1], item[0]))[0][0]
        profile_summaries.append(
            {
                "name": str(payload.get("profile", "")),
                "services": str(payload.get("services", "")),
                "outDir": str(payload.get("outDir", "")),
                "latestJson": str(Path(str(payload.get("outDir", ""))) / "latest.json"),
                "discovered": int(payload.get("discovered", 0) or 0),
                "processed": int(payload.get("processed", 0) or 0),
                "failures": int(payload.get("failures", 0) or 0),
                "metrics": _summarize_profile_metrics(rows),
                "slamModelPreferredMode": slam_model_preferred_mode,
            }
        )

    baseline_name = "baseline_reference"
    if not any(entry.get("name") == baseline_name for entry in profile_summaries):
        baseline_name = str(profile_summaries[0].get("name")) if profile_summaries else ""
    baseline_entry = next((entry for entry in profile_summaries if entry.get("name") == baseline_name), {})

    deltas: dict[str, Any] = {}
    baseline_metrics = baseline_entry.get("metrics")
    baseline_metrics = baseline_metrics if isinstance(baseline_metrics, dict) else {}
    for entry in profile_summaries:
        name = str(entry.get("name", ""))
        if not name or name == baseline_name:
            continue
        entry_metrics = entry.get("metrics")
        entry_metrics = entry_metrics if isinstance(entry_metrics, dict) else {}
        metric_deltas: dict[str, Any] = {}
        delta_flat: dict[str, Any] = {}
        for field in METRIC_FIELDS:
            base_stat = baseline_metrics.get(field)
            cur_stat = entry_metrics.get(field)
            base_stat = base_stat if isinstance(base_stat, dict) else {}
            cur_stat = cur_stat if isinstance(cur_stat, dict) else {}
            delta_stats: dict[str, Any] = {}
            for key in ("mean", "median", "p90"):
                base_val = _to_metric_number(base_stat.get(key))
                cur_val = _to_metric_number(cur_stat.get(key))
                delta_stats[key] = (cur_val - base_val) if (base_val is not None and cur_val is not None) else None
            metric_deltas[field] = delta_stats
            # keep a compact delta map for quick consumption.
            delta_flat[f"delta_{field}"] = delta_stats.get("p90")
            if delta_flat[f"delta_{field}"] is None:
                delta_flat[f"delta_{field}"] = delta_stats.get("mean")
        deltas[name] = {"metrics": metric_deltas, "deltaFlat": delta_flat}

    payload: dict[str, Any] = {
        "schemaVersion": "byes.dataset_benchmark.matrix.v1",
        "generatedAtMs": int(generated_at_ms),
        "root": str(root),
        "outDir": str(out_dir),
        "replay": bool(replay),
        "baselineProfile": baseline_name,
        "profiles": profile_summaries,
        "deltas": deltas,
        "discovered": sum(int(entry.get("discovered", 0) or 0) for entry in profile_summaries),
        "processed": sum(int(entry.get("processed", 0) or 0) for entry in profile_summaries),
        "failures": sum(int(entry.get("failures", 0) or 0) for entry in profile_summaries),
        "rows": combined_rows,
    }
    return payload


def _write_matrix_summary_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# Dataset Benchmark Matrix Summary")
    lines.append("")
    lines.append(f"- root: `{payload.get('root', '')}`")
    lines.append(f"- replay: `{payload.get('replay', False)}`")
    lines.append(f"- baselineProfile: `{payload.get('baselineProfile', '')}`")
    lines.append(f"- discovered: `{payload.get('discovered', 0)}`")
    lines.append(f"- processed: `{payload.get('processed', 0)}`")
    lines.append(f"- failures: `{payload.get('failures', 0)}`")
    lines.append("")
    lines.append("| profile | services | discovered | processed | failures | quality(mean) | riskP90(p90) | frameUserTtsP90(p90) | slamCoverage(mean) | slamAlignP90(p90) | slamATE(mean) | slamRPE(mean) | costmapCoverage(mean) | costmapLatencyP90(p90) | costmapFusedCoverage(mean) | costmapFusedIouP90(p90) | costmapFusedFlickerMean(mean) | costmapFusedShiftUsedRate(mean) | costmapFusedShiftRejectRate(mean) | slamModelPreferred(mode) | planCostmapUsedRate(mean) |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|")
    profiles = payload.get("profiles")
    profiles = profiles if isinstance(profiles, list) else []
    for entry in profiles:
        metrics = entry.get("metrics")
        metrics = metrics if isinstance(metrics, dict) else {}
        quality = metrics.get("qualityScore")
        quality = quality if isinstance(quality, dict) else {}
        risk = metrics.get("riskLatencyP90")
        risk = risk if isinstance(risk, dict) else {}
        tts = metrics.get("frame_user_e2e_tts_p90")
        tts = tts if isinstance(tts, dict) else {}
        slam_cov = metrics.get("slam_coverage")
        slam_cov = slam_cov if isinstance(slam_cov, dict) else {}
        slam_align = metrics.get("slam_align_residual_p90")
        slam_align = slam_align if isinstance(slam_align, dict) else {}
        slam_ate = metrics.get("slam_ate_rmse")
        slam_ate = slam_ate if isinstance(slam_ate, dict) else {}
        slam_rpe = metrics.get("slam_rpe_trans_rmse")
        slam_rpe = slam_rpe if isinstance(slam_rpe, dict) else {}
        costmap_cov = metrics.get("costmap_coverage")
        costmap_cov = costmap_cov if isinstance(costmap_cov, dict) else {}
        costmap_p90 = metrics.get("costmap_latency_p90")
        costmap_p90 = costmap_p90 if isinstance(costmap_p90, dict) else {}
        costmap_fused_cov = metrics.get("costmap_fused_coverage")
        costmap_fused_cov = costmap_fused_cov if isinstance(costmap_fused_cov, dict) else {}
        costmap_fused_iou = metrics.get("costmap_fused_iou_p90")
        costmap_fused_iou = costmap_fused_iou if isinstance(costmap_fused_iou, dict) else {}
        costmap_fused_flicker = metrics.get("costmap_fused_flicker_rate_mean")
        costmap_fused_flicker = costmap_fused_flicker if isinstance(costmap_fused_flicker, dict) else {}
        costmap_fused_shift_used = metrics.get("costmap_fused_shift_used_rate")
        costmap_fused_shift_used = costmap_fused_shift_used if isinstance(costmap_fused_shift_used, dict) else {}
        costmap_fused_shift_reject = metrics.get("costmap_fused_shift_gate_reject_rate")
        costmap_fused_shift_reject = (
            costmap_fused_shift_reject if isinstance(costmap_fused_shift_reject, dict) else {}
        )
        plan_costmap_used = metrics.get("plan_costmap_ctx_used_rate")
        plan_costmap_used = plan_costmap_used if isinstance(plan_costmap_used, dict) else {}
        lines.append(
            "| {name} | {services} | {d} | {p} | {f} | {quality} | {risk} | {tts} | {slam_cov} | {slam_align} | {slam_ate} | {slam_rpe} | {costmap_cov} | {costmap_p90} | {costmap_fused_cov} | {costmap_fused_iou} | {costmap_fused_flicker} | {costmap_fused_shift_used} | {costmap_fused_shift_reject} | {slam_model_preferred} | {plan_costmap_used} |".format(
                name=entry.get("name"),
                services=entry.get("services"),
                d=entry.get("discovered"),
                p=entry.get("processed"),
                f=entry.get("failures"),
                quality=quality.get("mean"),
                risk=risk.get("p90"),
                tts=tts.get("p90"),
                slam_cov=slam_cov.get("mean"),
                slam_align=slam_align.get("p90"),
                slam_ate=slam_ate.get("mean"),
                slam_rpe=slam_rpe.get("mean"),
                costmap_cov=costmap_cov.get("mean"),
                costmap_p90=costmap_p90.get("p90"),
                costmap_fused_cov=costmap_fused_cov.get("mean"),
                costmap_fused_iou=costmap_fused_iou.get("p90"),
                costmap_fused_flicker=costmap_fused_flicker.get("mean"),
                costmap_fused_shift_used=costmap_fused_shift_used.get("mean"),
                costmap_fused_shift_reject=costmap_fused_shift_reject.get("mean"),
                slam_model_preferred=entry.get("slamModelPreferredMode"),
                plan_costmap_used=plan_costmap_used.get("mean"),
            )
        )

    deltas = payload.get("deltas")
    deltas = deltas if isinstance(deltas, dict) else {}
    if deltas:
        lines.append("")
        lines.append("## Deltas vs baseline")
        lines.append("")
        lines.append("| profile | delta_qualityScore | delta_riskLatencyP90 | delta_frame_user_e2e_tts_p90 | delta_slam_coverage | delta_slam_align_residual_p90 | delta_slam_ate_rmse | delta_slam_rpe_trans_rmse | delta_costmap_coverage | delta_costmap_latency_p90 | delta_costmap_fused_coverage | delta_costmap_fused_iou_p90 | delta_costmap_fused_flicker_rate_mean | delta_costmap_fused_shift_used_rate | delta_costmap_fused_shift_gate_reject_rate | delta_plan_costmap_ctx_used_rate |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for name, value in deltas.items():
            block = value if isinstance(value, dict) else {}
            flat = block.get("deltaFlat")
            flat = flat if isinstance(flat, dict) else {}
            lines.append(
                "| {name} | {dq} | {dr} | {dt} | {ds} | {da} | {dsa} | {dsr} | {dcc} | {dcl} | {dcfc} | {dcfi} | {dcff} | {dcfsu} | {dcfsr} | {dpcu} |".format(
                    name=name,
                    dq=flat.get("delta_qualityScore"),
                    dr=flat.get("delta_riskLatencyP90"),
                    dt=flat.get("delta_frame_user_e2e_tts_p90"),
                    ds=flat.get("delta_slam_coverage"),
                    da=flat.get("delta_slam_align_residual_p90"),
                    dsa=flat.get("delta_slam_ate_rmse"),
                    dsr=flat.get("delta_slam_rpe_trans_rmse"),
                    dcc=flat.get("delta_costmap_coverage"),
                    dcl=flat.get("delta_costmap_latency_p90"),
                    dcfc=flat.get("delta_costmap_fused_coverage"),
                    dcfi=flat.get("delta_costmap_fused_iou_p90"),
                    dcff=flat.get("delta_costmap_fused_flicker_rate_mean"),
                    dcfsu=flat.get("delta_costmap_fused_shift_used_rate"),
                    dcfsr=flat.get("delta_costmap_fused_shift_gate_reject_rate"),
                    dpcu=flat.get("delta_plan_costmap_ctx_used_rate"),
                )
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_dataset_benchmark_matrix(
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
    base_services: dict[str, str],
    env_file: Path | None,
    profiles: list[BenchmarkProfile],
) -> tuple[dict[str, Any], int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    profile_payloads: list[dict[str, Any]] = []
    combined_rows: list[dict[str, Any]] = []
    any_failure = False
    start_ms = _now_ms()
    for profile in profiles:
        effective_services = dict(base_services)
        effective_services.update(profile.services)
        profile_out = out_dir / profile.name
        payload, profile_exit = run_dataset_benchmark(
            root=root,
            out_dir=profile_out,
            glob_pattern=glob_pattern,
            max_items=max_items,
            shuffle_items=shuffle_items,
            seed=seed,
            replay=replay,
            reset=reset,
            apply_scenario_calls=apply_scenario_calls,
            fail_on_drop=fail_on_drop,
            ports=ports,
            services=effective_services,
            env_file=env_file,
            profile_name=profile.name,
            env_overrides=profile.env,
            prehooks=profile.prehooks,
        )
        profile_payloads.append(payload)
        rows = payload.get("rows")
        if isinstance(rows, list):
            combined_rows.extend(rows)
        if profile_exit != 0:
            any_failure = True

    summary_payload = _build_matrix_summary_payload(
        root=root,
        out_dir=out_dir,
        replay=replay,
        profile_payloads=profile_payloads,
        generated_at_ms=_now_ms(),
    )
    summary_payload["durationMs"] = max(0, _now_ms() - start_ms)

    combined_payload = {
        "schemaVersion": "byes.dataset_benchmark.v1",
        "matrix": True,
        "generatedAtMs": summary_payload.get("generatedAtMs"),
        "durationMs": summary_payload.get("durationMs"),
        "root": str(root),
        "outDir": str(out_dir),
        "glob": glob_pattern,
        "replay": bool(replay),
        "profiles": [p.name for p in profiles],
        "discovered": int(summary_payload.get("discovered", 0) or 0),
        "processed": int(summary_payload.get("processed", 0) or 0),
        "failures": int(summary_payload.get("failures", 0) or 0),
        "rows": combined_rows,
    }
    _write_latest_bundle(out_dir=out_dir, payload=combined_payload, rows=combined_rows)
    (out_dir / "summary.json").write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_matrix_summary_markdown(out_dir / "summary.md", summary_payload)

    exit_code = 1 if (fail_on_drop and any_failure) else 0
    return summary_payload, exit_code


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch replay/report benchmark over run packages")
    parser.add_argument("--root", required=True, help="Root directory containing run packages")
    parser.add_argument(
        "--out",
        default=str(GATEWAY_ROOT / "artifacts" / "benchmarks" / f"v470_{_utc_compact()}"),
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
    parser.add_argument("--profiles", default="", help="Path to profiles.json for matrix runs")
    parser.add_argument("--profile", default="", help="Optional profile name filter for matrix mode")
    parser.add_argument("--matrix", type=int, default=0, help="Run all profiles in matrix mode (1/0)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    out_dir = Path(args.out).resolve()
    glob_pattern = str(args.glob or "**/manifest.json")
    max_items = int(args.max)
    shuffle_items = _parse_bool(args.shuffle)
    seed = int(args.seed)
    replay = _parse_bool(args.replay)
    reset = _parse_bool(args.reset)
    apply_scenario_calls = _parse_bool(args.apply_scenario_calls)
    fail_on_drop = _parse_bool(args.fail_on_drop)
    ports = _parse_ports(args.ports)
    services = _parse_services(args.services)
    env_file = Path(args.env_file).resolve() if str(args.env_file or "").strip() else None
    matrix_mode = _parse_bool(args.matrix)

    if matrix_mode:
        profiles_path_raw = str(args.profiles or "").strip()
        if not profiles_path_raw:
            raise SystemExit("--matrix=1 requires --profiles <path>")
        profiles = _load_profiles(Path(profiles_path_raw).resolve())
        profile_filter = str(args.profile or "").strip()
        if profile_filter:
            profiles = [p for p in profiles if p.name == profile_filter]
            if not profiles:
                raise SystemExit(f"profile not found in profiles file: {profile_filter}")
        payload, exit_code = run_dataset_benchmark_matrix(
            root=root,
            out_dir=out_dir,
            glob_pattern=glob_pattern,
            max_items=max_items,
            shuffle_items=shuffle_items,
            seed=seed,
            replay=replay,
            reset=reset,
            apply_scenario_calls=apply_scenario_calls,
            fail_on_drop=fail_on_drop,
            ports=ports,
            base_services=services,
            env_file=env_file,
            profiles=profiles,
        )
        summaries = payload.get("profiles")
        summaries = summaries if isinstance(summaries, list) else []
        for profile_summary in summaries:
            if not isinstance(profile_summary, dict):
                continue
            print(
                "[benchmark][profile={name}] discovered={d} processed={p} failures={f} replay={r}".format(
                    name=profile_summary.get("name"),
                    d=profile_summary.get("discovered", 0),
                    p=profile_summary.get("processed", 0),
                    f=profile_summary.get("failures", 0),
                    r=payload.get("replay", False),
                )
            )
        print(f"[out] {out_dir / 'summary.json'}")
        return int(exit_code)

    payload, exit_code = run_dataset_benchmark(
        root=root,
        out_dir=out_dir,
        glob_pattern=glob_pattern,
        max_items=max_items,
        shuffle_items=shuffle_items,
        seed=seed,
        replay=replay,
        reset=reset,
        apply_scenario_calls=apply_scenario_calls,
        fail_on_drop=fail_on_drop,
        ports=ports,
        services=services,
        env_file=env_file,
    )
    print(
        "[benchmark] discovered={d} processed={p} failures={f} replay={r}".format(
            d=payload.get("discovered", 0),
            p=payload.get("processed", 0),
            f=payload.get("failures", 0),
            r=payload.get("replay", False),
        )
    )
    print(f"[out] {out_dir / 'latest.json'}")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
