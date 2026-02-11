from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))

from byes.latency_stats import extract_risk_hazard_latencies, iter_jsonl, summarize_latency  # noqa: E402


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid bool value: {value}")


def _parse_sizes(raw: str) -> list[int]:
    sizes: list[int] = []
    for item in str(raw or "").split(","):
        text = item.strip()
        if not text:
            continue
        value = int(text)
        if value <= 0:
            continue
        sizes.append(value)
    if not sizes:
        raise argparse.ArgumentTypeError("sizes is empty")
    return sizes


def _load_manifest(run_package_dir: Path) -> dict[str, Any]:
    for name in ("manifest.json", "run_manifest.json"):
        path = run_package_dir / name
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
            break
    raise FileNotFoundError(f"manifest not found in run package: {run_package_dir}")


def _resolve_events_path_from_manifest(run_package_dir: Path, manifest: dict[str, Any]) -> Path | None:
    rel = str(manifest.get("eventsV1Jsonl", "")).strip()
    if rel:
        candidate = run_package_dir / rel
        if candidate.exists():
            return candidate
    autodetect = run_package_dir / "events" / "events_v1.jsonl"
    if autodetect.exists():
        return autodetect
    return None


def _check_inference_service(port: int, risk_url: str) -> tuple[bool, dict[str, Any], str]:
    health_url = f"http://127.0.0.1:{port}/healthz"
    try:
        with httpx.Client(timeout=3.0) as client:
            health_resp = client.get(health_url)
            health_resp.raise_for_status()
            payload = health_resp.json()
            if not isinstance(payload, dict):
                payload = {}
            risk_resp = client.post(risk_url, json={"image_b64": "", "frameSeq": 1})
            # risk endpoint may reject empty image; this still proves service is reachable.
            risk_ok = risk_resp.status_code in {200, 400, 422, 503}
            if not risk_ok:
                return False, payload, f"risk endpoint returned unexpected status={risk_resp.status_code}"
            return True, payload, ""
    except Exception as exc:  # noqa: BLE001
        return False, {}, str(exc)


def _required_env_hint(size: int) -> list[str]:
    return [
        "请先在 inference_service 进程环境设置：",
        "  BYES_SERVICE_RISK_PROVIDER=heuristic",
        "  BYES_SERVICE_DEPTH_PROVIDER=onnx",
        "  BYES_SERVICE_DEPTH_ONNX_PATH=<path_to_model.onnx>",
        f"  BYES_SERVICE_DEPTH_INPUT_SIZE={size}",
        f"  BYES_SERVICE_DEPTH_MODEL_ID=depth-anything-v2-small-onnx-s{size}",
        "  BYES_SERVICE_RISK_DEBUG=1",
    ]


def _run_replay(run_package: Path, out_dir: Path) -> tuple[bool, str]:
    script = THIS_DIR / "replay_run_package.py"
    cmd = [sys.executable, str(script), "--run-package", str(run_package), "--out-dir", str(out_dir), "--reset"]
    completed = subprocess.run(cmd, cwd=GATEWAY_ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return False, f"replay failed: {completed.stdout}\n{completed.stderr}".strip()
    return True, completed.stdout.strip()


def _pick_latest_subdir(path: Path) -> Path | None:
    if not path.exists():
        return None
    dirs = [p for p in path.iterdir() if p.is_dir()]
    if not dirs:
        return None
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs[0]


def _build_temp_report_package(source_run_package: Path, replay_events_path: Path, size: int) -> Path:
    temp_root = Path(tempfile.mkdtemp(prefix=f"depth_sweep_pkg_s{size}_"))
    shutil.copytree(source_run_package, temp_root, dirs_exist_ok=True)
    events_dir = temp_root / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(replay_events_path, events_dir / "events_v1.jsonl")

    manifest_path = temp_root / "manifest.json"
    if not manifest_path.exists():
        manifest_path = temp_root / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        manifest = {}
    manifest["eventsV1Jsonl"] = "events/events_v1.jsonl"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return temp_root


def _run_report(run_package: Path, out_json: Path, out_md: Path) -> tuple[bool, str]:
    script = THIS_DIR / "report_run.py"
    cmd = [
        sys.executable,
        str(script),
        "--run-package",
        str(run_package),
        "--output-json",
        str(out_json),
        "--output",
        str(out_md),
    ]
    completed = subprocess.run(cmd, cwd=GATEWAY_ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return False, f"report failed: {completed.stdout}\n{completed.stderr}".strip()
    return True, completed.stdout.strip()


def _recommend_size(records: list[dict[str, Any]]) -> tuple[int | None, str]:
    valid_records = [r for r in records if int(r.get("riskLatency", {}).get("count", 0) or 0) > 0]
    if not valid_records:
        return None, "no valid records"

    ordered = valid_records
    baseline_quality: float | None = None
    for row in ordered:
        q = row.get("qualityScore")
        if isinstance(q, (int, float)):
            baseline_quality = float(q)
            break

    if baseline_quality is not None:
        threshold = baseline_quality - 2.0
        candidates = [r for r in ordered if isinstance(r.get("qualityScore"), (int, float)) and float(r["qualityScore"]) >= threshold]
        if candidates:
            candidates.sort(
                key=lambda r: (
                    int(r.get("riskLatency", {}).get("p90", 0) or 0),
                    int(r.get("riskLatency", {}).get("p50", 0) or 0),
                    -float(r.get("qualityScore", 0.0) or 0.0),
                )
            )
            best = candidates[0]
            return int(best.get("size", 0) or 0), f"quality >= baseline-2 ({threshold:.2f}) and smallest p90"

    ordered = sorted(
        ordered,
        key=lambda r: (
            int(r.get("riskLatency", {}).get("p90", 0) or 0),
            int(r.get("riskLatency", {}).get("p50", 0) or 0),
        ),
    )
    best = ordered[0]
    return int(best.get("size", 0) or 0), "fallback: smallest p90"


def _render_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Depth Input Size Sweep")
    lines.append("")
    lines.append("| size | latency p50 | latency p90 | latency max | qualityScore | precision | recall | f1 | notes |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for row in payload.get("records", []):
        lat = row.get("riskLatency", {})
        overall = row.get("depthRiskOverall", {})
        notes = str(row.get("notes", "")).replace("\n", " ")
        lines.append(
            "| {size} | {p50} | {p90} | {m} | {q} | {pr} | {rc} | {f1} | {notes} |".format(
                size=row.get("size", ""),
                p50=lat.get("p50", 0),
                p90=lat.get("p90", 0),
                m=lat.get("max", 0),
                q=row.get("qualityScore", "n/a"),
                pr=overall.get("precision", "n/a"),
                rc=overall.get("recall", "n/a"),
                f1=overall.get("f1", "n/a"),
                notes=notes or "-",
            )
        )
    lines.append("")
    lines.append(f"- recommended size: `{payload.get('recommendedSize')}`")
    lines.append(f"- recommendation rule: `{payload.get('recommendationRule')}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep depth input sizes and summarize risk latency vs quality")
    parser.add_argument("--run-package", required=True, help="Run package directory")
    parser.add_argument("--sizes", default="518,384,256", help="Comma-separated depth input sizes")
    parser.add_argument("--out", default=str(GATEWAY_ROOT / "regression" / "out" / "depth_sweep_latest.json"))
    parser.add_argument("--port", type=int, default=19120)
    parser.add_argument("--risk-url", default="http://127.0.0.1:19120/risk")
    parser.add_argument("--use-http", type=_parse_bool, default=True)
    parser.add_argument("--fail-if-missing-model", type=_parse_bool, default=False)
    args = parser.parse_args()

    run_package = Path(args.run_package)
    if not run_package.exists() or not run_package.is_dir():
        print(f"run package not found: {run_package}")
        return 1

    sizes = _parse_sizes(args.sizes)
    out_json = Path(args.out)
    out_md = out_json.with_suffix(".md")
    out_json.parent.mkdir(parents=True, exist_ok=True)

    parsed_risk_url = urlparse(str(args.risk_url).strip())
    if not parsed_risk_url.scheme or not parsed_risk_url.netloc:
        print(f"invalid --risk-url: {args.risk_url}")
        return 1

    records: list[dict[str, Any]] = []
    use_http = bool(args.use_http)
    fail_if_missing_model = bool(args.fail_if_missing_model)

    for size in sizes:
        notes: list[str] = []
        if use_http:
            ok, health_payload, detail = _check_inference_service(args.port, args.risk_url)
            if not ok:
                notes.append("inference_service not reachable")
                if detail:
                    notes.append(detail)
                notes.extend(_required_env_hint(size))
                record = {
                    "size": size,
                    "riskLatency": summarize_latency([]),
                    "qualityScore": None,
                    "depthRiskOverall": {"precision": None, "recall": None, "f1": None},
                    "notes": "; ".join(notes),
                }
                records.append(record)
                if fail_if_missing_model:
                    break
                continue

            provider = str(health_payload.get("depthProvider", "")).strip().lower()
            model = str(health_payload.get("depthModel", "")).strip()
            if provider != "onnx":
                notes.append(f"depthProvider={provider or 'unknown'} (expected onnx)")
            if model and f"s{size}" not in model:
                notes.append(f"depthModel={model} (recommend suffix s{size})")

            # Optional local pre-check for model path in current shell.
            model_path_env = str(os.getenv("BYES_SERVICE_DEPTH_ONNX_PATH", "")).strip()
            if model_path_env and not Path(model_path_env).exists():
                notes.append(f"BYES_SERVICE_DEPTH_ONNX_PATH missing: {model_path_env}")
                if fail_if_missing_model:
                    records.append(
                        {
                            "size": size,
                            "riskLatency": summarize_latency([]),
                            "qualityScore": None,
                            "depthRiskOverall": {"precision": None, "recall": None, "f1": None},
                            "notes": "; ".join(notes),
                        }
                    )
                    break

            replay_root = out_json.parent / f"depth_sweep_runs_s{size}"
            replay_root.mkdir(parents=True, exist_ok=True)
            ok_replay, replay_output = _run_replay(run_package, replay_root)
            if not ok_replay:
                notes.append(replay_output)
                records.append(
                    {
                        "size": size,
                        "riskLatency": summarize_latency([]),
                        "qualityScore": None,
                        "depthRiskOverall": {"precision": None, "recall": None, "f1": None},
                        "notes": "; ".join(notes),
                    }
                )
                continue

            replay_dir = _pick_latest_subdir(replay_root)
            if replay_dir is None:
                notes.append("replay output dir not found")
                records.append(
                    {
                        "size": size,
                        "riskLatency": summarize_latency([]),
                        "qualityScore": None,
                        "depthRiskOverall": {"precision": None, "recall": None, "f1": None},
                        "notes": "; ".join(notes),
                    }
                )
                continue

            replay_events = replay_dir / "events" / "events_v1.jsonl"
            if not replay_events.exists():
                notes.append(f"events missing: {replay_events}")
                records.append(
                    {
                        "size": size,
                        "riskLatency": summarize_latency([]),
                        "qualityScore": None,
                        "depthRiskOverall": {"precision": None, "recall": None, "f1": None},
                        "notes": "; ".join(notes),
                    }
                )
                continue

            report_pkg = _build_temp_report_package(run_package, replay_events, size)
            try:
                report_json = out_json.parent / f"depth_sweep_report_s{size}.json"
                report_md = out_json.parent / f"depth_sweep_report_s{size}.md"
                ok_report, report_output = _run_report(report_pkg, report_json, report_md)
                if not ok_report:
                    notes.append(report_output)
                    quality_score = None
                    overall = {"precision": None, "recall": None, "f1": None}
                else:
                    report_payload = json.loads(report_json.read_text(encoding="utf-8-sig"))
                    quality = report_payload.get("quality", {}) if isinstance(report_payload, dict) else {}
                    quality_score = quality.get("qualityScore")
                    depth_risk = quality.get("depthRisk", {}) if isinstance(quality, dict) else {}
                    overall_raw = depth_risk.get("overall", {}) if isinstance(depth_risk, dict) else {}
                    overall = {
                        "precision": overall_raw.get("precision"),
                        "recall": overall_raw.get("recall"),
                        "f1": overall_raw.get("f1"),
                    }
            finally:
                shutil.rmtree(report_pkg, ignore_errors=True)

            latency_stats = summarize_latency(extract_risk_hazard_latencies(iter_jsonl(replay_events)))
            records.append(
                {
                    "size": size,
                    "riskLatency": latency_stats,
                    "qualityScore": quality_score,
                    "depthRiskOverall": overall,
                    "notes": "; ".join(notes),
                }
            )
        else:
            manifest = _load_manifest(run_package)
            events_path = _resolve_events_path_from_manifest(run_package, manifest)
            if events_path is None:
                notes.append("events/events_v1.jsonl not found in run package")
                latency_stats = summarize_latency([])
            else:
                latency_stats = summarize_latency(extract_risk_hazard_latencies(iter_jsonl(events_path)))

            report_json = out_json.parent / f"depth_sweep_report_s{size}.json"
            report_md = out_json.parent / f"depth_sweep_report_s{size}.md"
            ok_report, report_output = _run_report(run_package, report_json, report_md)
            if not ok_report:
                notes.append(report_output)
                quality_score = None
                overall = {"precision": None, "recall": None, "f1": None}
            else:
                report_payload = json.loads(report_json.read_text(encoding="utf-8-sig"))
                quality = report_payload.get("quality", {}) if isinstance(report_payload, dict) else {}
                quality_score = quality.get("qualityScore")
                depth_risk = quality.get("depthRisk", {}) if isinstance(quality, dict) else {}
                overall_raw = depth_risk.get("overall", {}) if isinstance(depth_risk, dict) else {}
                overall = {
                    "precision": overall_raw.get("precision"),
                    "recall": overall_raw.get("recall"),
                    "f1": overall_raw.get("f1"),
                }
            notes.append("use-http=false: report/latency from existing run package events")
            records.append(
                {
                    "size": size,
                    "riskLatency": latency_stats,
                    "qualityScore": quality_score,
                    "depthRiskOverall": overall,
                    "notes": "; ".join(notes),
                }
            )

    recommended_size, recommendation_rule = _recommend_size(records)
    payload = {
        "runPackage": str(run_package),
        "sizes": sizes,
        "useHttp": use_http,
        "riskUrl": args.risk_url,
        "records": records,
        "recommendedSize": recommended_size,
        "recommendationRule": recommendation_rule,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(_render_markdown(payload), encoding="utf-8")

    print(f"sweep json -> {out_json}")
    print(f"sweep md -> {out_md}")
    print(f"recommended size -> {recommended_size} ({recommendation_rule})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
