from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))

from byes.inference.prompt_budget import pack_prompt  # noqa: E402
from scripts.report_run import generate_report_outputs, resolve_run_package_input  # noqa: E402


def _parse_int_list(raw: str) -> list[int]:
    values: list[int] = []
    seen: set[int] = set()
    for chunk in str(raw or "").split(","):
        text = chunk.strip()
        if not text:
            continue
        value = int(text)
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        values.append(value)
    if not values:
        raise ValueError("empty budget list")
    return values


def _load_manifest(run_package_dir: Path) -> dict[str, Any]:
    for name in ("manifest.json", "run_manifest.json"):
        path = run_package_dir / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            return payload
    return {}


def _resolve_events_path(run_package_dir: Path, manifest: dict[str, Any]) -> Path:
    rel = str(manifest.get("eventsV1Jsonl", "")).strip()
    if rel:
        path = run_package_dir / rel
        if path.exists():
            return path
    fallback = run_package_dir / "events" / "events_v1.jsonl"
    if fallback.exists():
        return fallback
    raise FileNotFoundError("events/events_v1.jsonl not found")


def _iter_events(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _prompt_from_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    targets_count = _to_nonnegative_int(payload.get("targetsCount"))
    boxes_count = _to_nonnegative_int(payload.get("boxesCount"))
    points_count = _to_nonnegative_int(payload.get("pointsCount"))
    text_chars = _to_nonnegative_int(payload.get("textChars"))
    prompt_version = str(payload.get("promptVersion", "")).strip()

    prompt: dict[str, Any] = {}
    if targets_count > 0:
        prompt["targets"] = [f"target{i+1}" for i in range(targets_count)]
    if text_chars > 0:
        prompt["text"] = "x" * text_chars
    if boxes_count > 0:
        prompt["boxes"] = [[float(i), float(i), float(i + 10), float(i + 10)] for i in range(boxes_count)]
    if points_count > 0:
        prompt["points"] = [{"x": float(i), "y": float(i), "label": 1} for i in range(points_count)]
    if prompt_version:
        prompt["meta"] = {"promptVersion": prompt_version}
    return prompt


def _to_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except Exception:
        return 0


def _extract_prompt_payloads(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if str(event.get("name", "")).strip().lower() != "seg.prompt":
            continue
        if str(event.get("phase", "")).strip().lower() != "result":
            continue
        if str(event.get("status", "")).strip().lower() != "ok":
            continue
        payload = event.get("payload")
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _extract_metrics(report_payload: dict[str, Any]) -> dict[str, Any]:
    quality = report_payload.get("quality", {})
    quality = quality if isinstance(quality, dict) else {}
    seg = quality.get("seg", {})
    seg = seg if isinstance(seg, dict) else {}
    risk_latency = quality.get("riskLatencyMs", {})
    risk_latency = risk_latency if isinstance(risk_latency, dict) else {}
    depth_risk = quality.get("depthRisk", {})
    depth_risk = depth_risk if isinstance(depth_risk, dict) else {}
    critical = depth_risk.get("critical", {})
    critical = critical if isinstance(critical, dict) else {}
    return {
        "qualityScore": _to_float(quality.get("qualityScore")),
        "critical_fn": _to_nonnegative_int(critical.get("missCriticalCount")),
        "riskLatencyP90": _to_nonnegative_int(risk_latency.get("p90")),
        "segCoverage": _to_float(seg.get("coverage")),
    }


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _recommend(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if float(row.get("metrics", {}).get("segCoverage") or 0.0) >= 1.0]
    if not eligible:
        eligible = rows

    def key_fn(row: dict[str, Any]) -> tuple[float, float, float]:
        metrics = row.get("metrics", {})
        trunc_rate = float(metrics.get("seg_prompt_trunc_rate") or 0.0)
        risk_latency = float(metrics.get("riskLatencyP90") or 0.0)
        quality_score = float(metrics.get("qualityScore") or 0.0)
        return (trunc_rate, risk_latency, -quality_score)

    best = sorted(eligible, key=key_fn)[0] if eligible else None
    return {
        "rule": "minimize seg_prompt_trunc_rate subject to segCoverage==1 then minimize riskLatencyP90 then maximize qualityScore",
        "bestMaxChars": int(best.get("maxChars", 0) or 0) if isinstance(best, dict) else None,
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Seg Prompt Budget Sweep",
        "",
        f"- runPackage: `{payload.get('runPackage', '')}`",
        f"- mode: `{payload.get('mode', '')}`",
        "",
        "| maxChars | truncRate | dropped | qualityScore | segCoverage | riskLatencyP90 |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload.get("rows", []):
        metrics = row.get("metrics", {})
        lines.append(
            "| {max_chars} | {trunc:.4f} | {dropped} | {quality} | {coverage} | {latency} |".format(
                max_chars=row.get("maxChars"),
                trunc=float(metrics.get("seg_prompt_trunc_rate") or 0.0),
                dropped=int(metrics.get("seg_prompt_trunc_dropped") or 0),
                quality=metrics.get("qualityScore"),
                coverage=metrics.get("segCoverage"),
                latency=metrics.get("riskLatencyP90"),
            )
        )
    lines.append("")
    recommendation = payload.get("recommendation", {})
    lines.append(f"- recommendation: `{recommendation.get('bestMaxChars', None)}`")
    lines.append(f"- rule: {recommendation.get('rule', '')}")
    return "\n".join(lines) + "\n"


def run_sweep(
    *,
    run_package: Path,
    max_chars_values: list[int],
    mode: str,
    max_targets: int,
    max_boxes: int,
    max_points: int,
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ws_jsonl, metrics_before, metrics_after, run_package_summary, cleanup_dir = resolve_run_package_input(run_package)
    try:
        run_package_dir = Path(str(run_package_summary.get("runPackageDir", "")).strip())
        manifest = _load_manifest(run_package_dir)
        events_path = _resolve_events_path(run_package_dir, manifest)
        events = _iter_events(events_path)
        prompt_payloads = _extract_prompt_payloads(events)

        report_json = out_dir / "report_base.json"
        report_md = out_dir / "report_base.md"
        _output_md, _output_json, report_payload = generate_report_outputs(
            ws_jsonl=ws_jsonl,
            output=report_md,
            output_json=report_json,
            metrics_url="http://127.0.0.1:8000/metrics",
            metrics_before_path=metrics_before,
            metrics_after_path=metrics_after,
            external_readiness_url=None,
            run_package_summary=run_package_summary,
        )
        base_metrics = _extract_metrics(report_payload)

        rows: list[dict[str, Any]] = []
        for max_chars in max_chars_values:
            trunc_dropped_total = 0
            items_total = 0
            for payload in prompt_payloads:
                prompt = _prompt_from_event_payload(payload)
                packed, stats = pack_prompt(
                    prompt,
                    budget={
                        "maxChars": max_chars,
                        "maxTargets": max_targets,
                        "maxBoxes": max_boxes,
                        "maxPoints": max_points,
                        "mode": mode,
                    },
                )
                del packed
                trunc = stats.get("truncation", {}) if isinstance(stats, dict) else {}
                in_stats = stats.get("in", {}) if isinstance(stats, dict) else {}
                dropped = (
                    _to_nonnegative_int(trunc.get("targetsDropped"))
                    + _to_nonnegative_int(trunc.get("boxesDropped"))
                    + _to_nonnegative_int(trunc.get("pointsDropped"))
                )
                items = (
                    _to_nonnegative_int(in_stats.get("targets"))
                    + _to_nonnegative_int(in_stats.get("boxes"))
                    + _to_nonnegative_int(in_stats.get("points"))
                )
                trunc_dropped_total += dropped
                items_total += items

            trunc_rate = float(trunc_dropped_total) / float(items_total) if items_total > 0 else 0.0
            metrics = dict(base_metrics)
            metrics["seg_prompt_trunc_dropped"] = trunc_dropped_total
            metrics["seg_prompt_trunc_rate"] = round(trunc_rate, 6)
            rows.append(
                {
                    "maxChars": int(max_chars),
                    "budget": {
                        "maxChars": int(max_chars),
                        "maxTargets": int(max_targets),
                        "maxBoxes": int(max_boxes),
                        "maxPoints": int(max_points),
                        "mode": str(mode),
                    },
                    "metrics": metrics,
                }
            )

        payload = {
            "schemaVersion": "byes.sweep.seg_prompt_budget.v1",
            "runPackage": str(run_package),
            "mode": str(mode),
            "rows": rows,
        }
        payload["recommendation"] = _recommend(rows)
        return payload
    finally:
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sweep seg prompt budgets and emit latest.json/latest.md.")
    parser.add_argument("--run-package", required=True)
    parser.add_argument("--max-chars", default="64,128,256", help="Comma-separated maxChars candidates")
    parser.add_argument("--mode", default="targets_text_boxes_points")
    parser.add_argument("--max-targets", type=int, default=8)
    parser.add_argument("--max-boxes", type=int, default=4)
    parser.add_argument("--max-points", type=int, default=8)
    parser.add_argument(
        "--out",
        default=str(Path(tempfile.gettempdir()) / "byes_seg_prompt_budget"),
        help="Output directory for latest.json/latest.md",
    )
    args = parser.parse_args(argv)

    payload = run_sweep(
        run_package=Path(args.run_package),
        max_chars_values=_parse_int_list(args.max_chars),
        mode=str(args.mode),
        max_targets=max(0, int(args.max_targets)),
        max_boxes=max(0, int(args.max_boxes)),
        max_points=max(0, int(args.max_points)),
        out_dir=Path(args.out),
    )
    out_dir = Path(args.out)
    latest_json = out_dir / "latest.json"
    latest_md = out_dir / "latest.md"
    latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest_md.write_text(_render_markdown(payload), encoding="utf-8")
    recommendation = payload.get("recommendation", {})
    print(f"[sweep] runPackage={payload.get('runPackage', '')} mode={payload.get('mode', '')}")
    print(f"[recommendation] bestMaxChars={recommendation.get('bestMaxChars', None)}")
    print(f"[rule] {recommendation.get('rule', '')}")
    print(f"[out] {latest_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
