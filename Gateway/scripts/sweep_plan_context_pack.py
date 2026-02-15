from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))

from byes.inference.plan_context_pack import (  # noqa: E402
    DEFAULT_PLAN_CONTEXT_PACK_BUDGET,
    PLAN_CONTEXT_PACK_MODES,
    build_plan_context_pack,
)
from byes.inference.seg_context import DEFAULT_SEG_CONTEXT_BUDGET, build_seg_context_from_events  # noqa: E402
from byes.plan_pipeline import extract_risk_summary, load_events_v1_rows  # noqa: E402
from byes.pov_context import build_context_pack, finalize_context_pack_text, render_context_text  # noqa: E402
from byes.pov_metrics import load_pov_ir_from_run_package  # noqa: E402


_DEFAULT_MODES = [
    "seg_plus_pov_plus_risk",
    "pov_plus_risk",
    "risk_only",
]


def _parse_int_csv(raw: str) -> list[int]:
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
        raise ValueError("budgets is empty")
    return values


def _parse_modes_csv(raw: str | None) -> list[str]:
    if raw is None or not str(raw).strip():
        return list(_DEFAULT_MODES)
    values: list[str] = []
    seen: set[str] = set()
    allowed = set(PLAN_CONTEXT_PACK_MODES)
    for chunk in str(raw).split(","):
        text = chunk.strip()
        if not text or text in seen:
            continue
        if text not in allowed:
            raise ValueError(f"invalid mode: {text}")
        seen.add(text)
        values.append(text)
    if not values:
        raise ValueError("modes is empty")
    return values


def _read_manifest(run_package: Path) -> dict[str, Any]:
    for name in ("manifest.json", "run_manifest.json"):
        path = run_package / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            return payload
    return {}


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _pick_run_id(run_package: Path, manifest: dict[str, Any], events_rows: list[dict[str, Any]]) -> str:
    run_id = str(manifest.get("runId", "")).strip()
    if run_id:
        return run_id
    for row in events_rows:
        rid = str(row.get("runId", "")).strip()
        if rid:
            return rid
    return run_package.name


def _append_plan_context_event(run_package: Path, context_pack: dict[str, Any], run_id: str) -> None:
    manifest = _read_manifest(run_package)
    events_rel = str(manifest.get("eventsV1Jsonl", "events/events_v1.jsonl")).strip() or "events/events_v1.jsonl"
    events_path = run_package / events_rel
    events_path.parent.mkdir(parents=True, exist_ok=True)

    latest_ts = int(time.time() * 1000)
    frame_seq = 1
    if events_path.exists():
        with events_path.open("r", encoding="utf-8-sig") as fp:
            for raw in fp:
                line = raw.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if not isinstance(row, dict):
                    continue
                ts_raw = _to_int(row.get("tsMs"))
                if isinstance(ts_raw, int):
                    latest_ts = max(latest_ts, ts_raw)
                seq_raw = _to_int(row.get("frameSeq"))
                if isinstance(seq_raw, int) and seq_raw > 0:
                    frame_seq = max(frame_seq, seq_raw)

    event = {
        "schemaVersion": "byes.event.v1",
        "tsMs": int(latest_ts + 1),
        "runId": run_id,
        "frameSeq": int(frame_seq),
        "component": "gateway",
        "category": "plan",
        "name": "plan.context_pack",
        "phase": "result",
        "status": "ok",
        "latencyMs": 1,
        "payload": context_pack,
    }
    with events_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(event, ensure_ascii=False) + "\n")


def _build_plan_context_for_combo(
    *,
    run_package: Path,
    run_id: str,
    events_rows: list[dict[str, Any]],
    pov_ir: dict[str, Any] | None,
    max_chars: int,
    mode: str,
) -> dict[str, Any]:
    seg_context_budget = {
        "maxChars": int(DEFAULT_SEG_CONTEXT_BUDGET["maxChars"]),
        "maxSegments": int(DEFAULT_SEG_CONTEXT_BUDGET["maxSegments"]),
        "mode": str(DEFAULT_SEG_CONTEXT_BUDGET["mode"]),
    }
    seg_context_raw = build_seg_context_from_events(events_rows, budget=seg_context_budget)
    seg_stats = seg_context_raw.get("stats")
    seg_stats = seg_stats if isinstance(seg_stats, dict) else {}
    seg_out = seg_stats.get("out")
    seg_out = seg_out if isinstance(seg_out, dict) else {}
    seg_context = seg_context_raw if int(seg_out.get("segments", 0) or 0) > 0 else None

    pov_context: dict[str, Any] | None = None
    if isinstance(pov_ir, dict):
        pov_budget = {"maxChars": 2000, "maxTokensApprox": 500}
        pov_pack = build_context_pack(pov_ir, budget=pov_budget, mode="decisions_plus_highlights")
        pov_text = render_context_text(pov_pack)
        pov_context = finalize_context_pack_text(pov_pack, pov_text, int(time.time() * 1000))

    risk_summary = extract_risk_summary(events_rows, frame_seq=None)
    budget = {"maxChars": int(max_chars), "mode": mode}
    return build_plan_context_pack(
        run_id=run_id,
        seg_context=seg_context,
        pov_context=pov_context,
        risk_context=risk_summary,
        budget=budget,
    )


def _run_report(run_package: Path, output_json: Path, output_md: Path) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(THIS_DIR / "report_run.py"),
        "--run-package",
        str(run_package),
        "--output-json",
        str(output_json),
        "--output",
        str(output_md),
    ]
    result = subprocess.run(cmd, cwd=GATEWAY_ROOT, capture_output=True, text=True, check=False)
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stderr:
        stdout = f"{stdout}\n{stderr}".strip()
    return int(result.returncode), stdout


def _extract_combo_metrics(report_payload: dict[str, Any]) -> dict[str, Any]:
    quality = report_payload.get("quality")
    quality = quality if isinstance(quality, dict) else {}
    quality_score = quality.get("qualityScore")
    if quality_score is None:
        quality_score = report_payload.get("qualityScore")

    plan_context_pack = report_payload.get("planContextPack")
    plan_context_pack = plan_context_pack if isinstance(plan_context_pack, dict) else {}
    out = plan_context_pack.get("out")
    out = out if isinstance(out, dict) else {}
    trunc = plan_context_pack.get("truncation")
    trunc = trunc if isinstance(trunc, dict) else {}

    plan_eval = report_payload.get("planEval")
    plan_eval = plan_eval if isinstance(plan_eval, dict) else {}
    confirm = plan_eval.get("confirm")
    confirm = confirm if isinstance(confirm, dict) else {}
    overcautious = plan_eval.get("overcautious")
    overcautious = overcautious if isinstance(overcautious, dict) else {}
    latency_ms = plan_eval.get("latencyMs")
    latency_ms = latency_ms if isinstance(latency_ms, dict) else {}
    frame_e2e = report_payload.get("frameE2E")
    frame_e2e = frame_e2e if isinstance(frame_e2e, dict) else {}
    frame_total = frame_e2e.get("totalMs")
    frame_total = frame_total if isinstance(frame_total, dict) else {}

    return {
        "qualityScore": _to_float(quality_score),
        "charsTotalP90": _to_int(out.get("charsTotalP90")),
        "truncationRate": _to_float(trunc.get("truncationRate")),
        "confirmTimeouts": _to_int(confirm.get("timeouts")),
        "overcautiousRate": _to_float(overcautious.get("rate")),
        "planLatencyP90": _to_int(latency_ms.get("p90")),
        "frameE2EP90": _to_int(frame_total.get("p90")),
    }


def _recommend(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "rule": "minimize confirm_timeouts -> truncation<=0.1 -> min frame_e2e_p90 -> min plan_latency_p90 -> max qualityScore",
            "best": None,
        }

    def confirm_value(row: dict[str, Any]) -> int:
        value = _to_int(row.get("metrics", {}).get("confirmTimeouts"))
        return 0 if value is None else max(0, value)

    def trunc_value(row: dict[str, Any]) -> float:
        value = _to_float(row.get("metrics", {}).get("truncationRate"))
        return 1.0 if value is None else max(0.0, value)

    min_confirm = min(confirm_value(row) for row in rows)
    stage = [row for row in rows if confirm_value(row) == min_confirm]

    feasible = [row for row in stage if trunc_value(row) <= 0.1]
    if not feasible:
        min_trunc = min(trunc_value(row) for row in stage)
        feasible = [row for row in stage if trunc_value(row) == min_trunc]

    frame_latency_values = [
        _to_int(row.get("metrics", {}).get("frameE2EP90"))
        for row in feasible
        if _to_int(row.get("metrics", {}).get("frameE2EP90")) is not None
    ]
    if frame_latency_values:
        best_frame_latency = min(frame_latency_values)
        feasible = [
            row
            for row in feasible
            if (_to_int(row.get("metrics", {}).get("frameE2EP90")) or best_frame_latency) == best_frame_latency
        ]

    latency_values = [
        _to_int(row.get("metrics", {}).get("planLatencyP90"))
        for row in feasible
        if _to_int(row.get("metrics", {}).get("planLatencyP90")) is not None
    ]
    if latency_values:
        best_latency = min(latency_values)
        feasible = [
            row
            for row in feasible
            if (_to_int(row.get("metrics", {}).get("planLatencyP90")) or best_latency) == best_latency
        ]

    quality_values = [
        _to_float(row.get("metrics", {}).get("qualityScore"))
        for row in feasible
        if _to_float(row.get("metrics", {}).get("qualityScore")) is not None
    ]
    if quality_values:
        best_quality = max(quality_values)
        feasible = [
            row
            for row in feasible
            if (_to_float(row.get("metrics", {}).get("qualityScore")) or best_quality) == best_quality
        ]

    feasible.sort(key=lambda row: (int(row.get("maxChars", 0) or 0), str(row.get("mode", ""))))
    best = feasible[0]
    rule = "minimize confirm_timeouts -> truncation<=0.1 -> min plan_latency_p90 -> max qualityScore"
    if frame_latency_values:
        rule = "minimize confirm_timeouts -> truncation<=0.1 -> min frame_e2e_p90 -> min plan_latency_p90 -> max qualityScore"
    return {
        "rule": rule,
        "best": {
            "maxChars": int(best.get("maxChars", 0) or 0),
            "mode": str(best.get("mode", "")),
        },
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Plan Context Pack Sweep",
        "",
        f"- runPackage: `{payload.get('runPackage', '')}`",
        f"- budgets: `{payload.get('budgets', [])}`",
        f"- modes: `{payload.get('modes', [])}`",
        "",
        "| maxChars | mode | charsP90 | truncRate | confirmTimeouts | frameE2EP90 | planLatencyP90 | qualityScore | overcautiousRate | notes |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in payload.get("rows", []):
        metrics = row.get("metrics", {})
        metrics = metrics if isinstance(metrics, dict) else {}

        def fmt(value: Any) -> str:
            return "missing" if value is None else str(value)

        trunc = metrics.get("truncationRate")
        trunc_text = "missing" if trunc is None else f"{float(trunc):.4f}"
        overcautious = metrics.get("overcautiousRate")
        overcautious_text = "missing" if overcautious is None else f"{float(overcautious):.4f}"

        lines.append(
            "| {max_chars} | {mode} | {chars} | {trunc} | {timeouts} | {frame_e2e} | {latency} | {quality} | {over} | {notes} |".format(
                max_chars=row.get("maxChars"),
                mode=row.get("mode"),
                chars=fmt(metrics.get("charsTotalP90")),
                trunc=trunc_text,
                timeouts=fmt(metrics.get("confirmTimeouts")),
                frame_e2e=fmt(metrics.get("frameE2EP90")),
                latency=fmt(metrics.get("planLatencyP90")),
                quality=fmt(metrics.get("qualityScore")),
                over=overcautious_text,
                notes=str(row.get("notes", "")).replace("\n", " "),
            )
        )
    lines.append("")
    lines.append(f"- recommendation: `{json.dumps(payload.get('recommendation', {}), ensure_ascii=False)}`")
    return "\n".join(lines) + "\n"


def evaluate_combo(
    *,
    source_run_package: Path,
    out_dir: Path,
    max_chars: int,
    mode: str,
) -> dict[str, Any]:
    run_pkg_tmp = Path(tempfile.mkdtemp(prefix="plan_ctx_combo_"))
    combo_name = f"{max_chars}_{mode}".replace("/", "_")
    combo_package = run_pkg_tmp / source_run_package.name
    shutil.copytree(source_run_package, combo_package)

    row: dict[str, Any] = {
        "maxChars": int(max_chars),
        "mode": str(mode),
        "metrics": {
            "charsTotalP90": None,
            "truncationRate": None,
            "confirmTimeouts": None,
            "frameE2EP90": None,
            "planLatencyP90": None,
            "qualityScore": None,
            "overcautiousRate": None,
        },
        "notes": "ok",
    }

    try:
        manifest = _read_manifest(combo_package)
        events_rows, _ = load_events_v1_rows(combo_package, manifest)
        run_id = _pick_run_id(combo_package, manifest, events_rows)
        pov_ir = load_pov_ir_from_run_package(combo_package)
        context_pack = _build_plan_context_for_combo(
            run_package=combo_package,
            run_id=run_id,
            events_rows=events_rows,
            pov_ir=pov_ir,
            max_chars=max_chars,
            mode=mode,
        )
        _append_plan_context_event(combo_package, context_pack, run_id)

        report_json = out_dir / f"report_{combo_name}.json"
        report_md = out_dir / f"report_{combo_name}.md"
        code, stdout = _run_report(combo_package, report_json, report_md)
        if code != 0:
            row["notes"] = f"report_failed:{code}"
            row["stdout"] = stdout
            return row

        payload = json.loads(report_json.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            row["notes"] = "report_payload_invalid"
            return row
        row["metrics"] = _extract_combo_metrics(payload)
        return row
    except Exception as exc:  # noqa: BLE001
        row["notes"] = f"error:{exc}"
        return row
    finally:
        shutil.rmtree(run_pkg_tmp, ignore_errors=True)


def run_sweep(
    *,
    run_package: Path,
    budgets: list[int],
    modes: list[str],
    out_dir: Path,
    port: int,
) -> dict[str, Any]:
    del port  # reserved for future online sweep mode
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for max_chars in budgets:
        for mode in modes:
            rows.append(evaluate_combo(source_run_package=run_package, out_dir=out_dir, max_chars=max_chars, mode=mode))

    recommendation = _recommend(rows)
    payload = {
        "schemaVersion": "byes.plan_context_pack.sweep.v1",
        "runPackage": str(run_package),
        "budgets": [int(v) for v in budgets],
        "modes": [str(v) for v in modes],
        "rows": rows,
        "recommendation": recommendation,
    }

    latest_json = out_dir / "latest.json"
    latest_md = out_dir / "latest.md"
    latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest_md.write_text(_render_markdown(payload), encoding="utf-8")

    print(json.dumps({"outJson": str(latest_json), "outMd": str(latest_md)}, ensure_ascii=False))
    print(f"[recommendation] {json.dumps(recommendation, ensure_ascii=False)}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep plan context pack budget/mode and recommend defaults")
    parser.add_argument("--run-package", required=True)
    parser.add_argument("--budgets", default="128,256,512")
    parser.add_argument("--modes", default=None)
    parser.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "byes_plan_ctx_sweep"))
    parser.add_argument("--port", type=int, default=19100)
    args = parser.parse_args()

    run_package = Path(args.run_package)
    if not run_package.exists() or not run_package.is_dir():
        print(f"run package not found: {run_package}")
        return 1

    try:
        budgets = _parse_int_csv(args.budgets)
        modes = _parse_modes_csv(args.modes)
    except Exception as exc:  # noqa: BLE001
        print(f"invalid args: {exc}")
        return 1

    out_dir = Path(args.out)
    try:
        run_sweep(
            run_package=run_package,
            budgets=budgets,
            modes=modes,
            out_dir=out_dir,
            port=int(args.port),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"sweep failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
