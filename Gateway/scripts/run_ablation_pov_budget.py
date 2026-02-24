from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))

from byes.pov_context import build_context_pack, finalize_context_pack_text, render_context_text  # noqa: E402
from byes.pov_metrics import load_pov_ir_from_run_package  # noqa: E402
from scripts.report_run import generate_report_outputs, resolve_run_package_input  # noqa: E402


def _now_ms() -> int:
    return int(time.time() * 1000)


def _parse_budgets(raw: str) -> list[int]:
    budgets: list[int] = []
    seen: set[int] = set()
    for chunk in str(raw or "").split(","):
        text = chunk.strip()
        if not text:
            continue
        value = int(text)
        if value <= 0:
            continue
        if value in seen:
            continue
        seen.add(value)
        budgets.append(value)
    if not budgets:
        raise ValueError("budgets must contain at least one positive integer")
    return budgets


def _parse_bool01(raw: str | int | bool) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return raw != 0
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _read_quality_metrics(report_payload: dict[str, Any]) -> dict[str, Any]:
    quality = report_payload.get("quality", {})
    quality = quality if isinstance(quality, dict) else {}

    depth_risk = quality.get("depthRisk", {})
    depth_risk = depth_risk if isinstance(depth_risk, dict) else {}
    critical = depth_risk.get("critical", {})
    critical = critical if isinstance(critical, dict) else {}
    delay = depth_risk.get("detectionDelayFrames", {})
    delay = delay if isinstance(delay, dict) else {}
    risk_latency = quality.get("riskLatencyMs", {})
    risk_latency = risk_latency if isinstance(risk_latency, dict) else {}

    miss_critical = _as_int_or_none(critical.get("missCriticalCount"))
    return {
        "qualityScore": _as_float_or_none(quality.get("qualityScore")),
        "critical_fn": miss_critical,
        "missCriticalCount": miss_critical,
        "riskLatencyP90": _as_int_or_none(risk_latency.get("p90")),
        "riskDelayP90": _as_int_or_none(delay.get("p90")),
    }


def _as_int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _as_float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _build_context_direct(
    *,
    pov_ir: dict[str, Any],
    max_chars: int,
    max_tokens_approx: int,
    mode: str,
) -> dict[str, Any]:
    pack = build_context_pack(
        pov_ir,
        budget={"maxChars": int(max_chars), "maxTokensApprox": int(max_tokens_approx)},
        mode=mode,
    )
    text_payload = render_context_text(pack)
    return finalize_context_pack_text(pack, text_payload, _now_ms())


def _build_context_http(
    *,
    run_package_dir: Path,
    max_chars: int,
    max_tokens_approx: int,
    mode: str,
) -> dict[str, Any]:
    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            "http://127.0.0.1:8000/api/pov/context",
            json={
                "runPackage": str(run_package_dir),
                "budget": {"maxChars": int(max_chars), "maxTokensApprox": int(max_tokens_approx)},
                "mode": mode,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("invalid /api/pov/context response")
        return payload


def _recommend(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def critical_val(row: dict[str, Any]) -> int:
        value = row.get("metrics", {}).get("critical_fn")
        return int(value) if isinstance(value, int) else 0

    eligible = [row for row in rows if critical_val(row) == 0]
    chosen = eligible if eligible else rows

    def key_fn(row: dict[str, Any]) -> tuple[float, float, int]:
        metrics = row.get("metrics", {})
        risk_latency = metrics.get("riskLatencyP90")
        if isinstance(risk_latency, int):
            risk_rank = float(risk_latency)
        else:
            risk_rank = 1e12
        quality = metrics.get("qualityScore")
        quality_rank = -float(quality) if isinstance(quality, (int, float)) else 1e12
        budget_tok = int(row.get("maxTokensApprox", 0) or 0)
        return (risk_rank, quality_rank, budget_tok)

    best = sorted(chosen, key=key_fn)[0] if chosen else None
    return {
        "rule": "minimize riskLatencyP90 subject to critical_fn==0 then maximize qualityScore",
        "bestMaxTokensApprox": int(best.get("maxTokensApprox", 0)) if isinstance(best, dict) else None,
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    rows = payload.get("rows", [])
    lines: list[str] = []
    lines.append("# POV Budget Ablation")
    lines.append("")
    lines.append(f"- runPackage: `{payload.get('runPackage', '')}`")
    lines.append(f"- mode: `{payload.get('mode', '')}`")
    lines.append(f"- budgets: `{payload.get('budgets', [])}`")
    lines.append("")
    lines.append("| budgetTok | ctxTok | ctxChars | decisions | highlights | qualityScore | critical_fn | riskLatencyP90 | riskDelayP90 |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        context = row.get("context", {})
        metrics = row.get("metrics", {})
        lines.append(
            "| {b} | {ctx_tok} | {ctx_chars} | {d} | {h} | {q} | {cfn} | {lat} | {delay} |".format(
                b=row.get("maxTokensApprox"),
                ctx_tok=context.get("tokenApprox"),
                ctx_chars=context.get("charsTotal"),
                d=context.get("decisions"),
                h=context.get("highlights"),
                q=metrics.get("qualityScore"),
                cfn=metrics.get("critical_fn"),
                lat=metrics.get("riskLatencyP90"),
                delay=metrics.get("riskDelayP90"),
            )
        )
    lines.append("")
    recommendation = payload.get("recommendation", {})
    lines.append(f"- recommendation: `{recommendation.get('bestMaxTokensApprox', None)}`")
    lines.append(f"- rule: {recommendation.get('rule', '')}")
    return "\n".join(lines) + "\n"


def run_ablation(
    *,
    run_package: Path,
    budgets: list[int],
    mode: str,
    out_dir: Path,
    use_http: bool,
    fail_on_critical_fn: bool,
) -> tuple[dict[str, Any], int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_package_resolved = run_package.resolve()

    ws_jsonl, metrics_before, metrics_after, run_package_summary, cleanup_dir = resolve_run_package_input(run_package_resolved)
    run_package_dir = Path(str(run_package_summary.get("runPackageDir", "")).strip())
    if not run_package_dir.exists():
        raise FileNotFoundError(f"run package dir not found: {run_package_dir}")
    pov_ir = load_pov_ir_from_run_package(run_package_dir)
    if not isinstance(pov_ir, dict):
        raise FileNotFoundError("povIrJson not found in run package manifest")

    rows: list[dict[str, Any]] = []
    critical_fn_failed = False

    try:
        for budget_tok in budgets:
            max_chars = min(4000, int(budget_tok) * 4)
            if use_http:
                context_pack = _build_context_http(
                    run_package_dir=run_package_dir,
                    max_chars=max_chars,
                    max_tokens_approx=int(budget_tok),
                    mode=mode,
                )
            else:
                context_pack = _build_context_direct(
                    pov_ir=pov_ir,
                    max_chars=max_chars,
                    max_tokens_approx=int(budget_tok),
                    mode=mode,
                )

            report_md = out_dir / f"report_tok_{budget_tok}.md"
            report_json = out_dir / f"report_tok_{budget_tok}.json"
            _out_md, _out_json, report_payload = generate_report_outputs(
                ws_jsonl=ws_jsonl,
                output=report_md,
                metrics_url="http://127.0.0.1:8000/metrics",
                metrics_before_path=metrics_before,
                metrics_after_path=metrics_after,
                external_readiness_url=None,
                run_package_summary=run_package_summary,
                output_json=report_json,
            )
            metrics = _read_quality_metrics(report_payload)
            critical_fn = metrics.get("critical_fn")
            if isinstance(critical_fn, int) and critical_fn > 0:
                critical_fn_failed = True

            stats = context_pack.get("stats", {})
            stats = stats if isinstance(stats, dict) else {}
            out_stats = stats.get("out", {})
            out_stats = out_stats if isinstance(out_stats, dict) else {}
            truncation = stats.get("truncation", {})
            truncation = truncation if isinstance(truncation, dict) else {}
            rows.append(
                {
                    "maxTokensApprox": int(budget_tok),
                    "maxChars": int(max_chars),
                    "context": {
                        "charsTotal": int(out_stats.get("charsTotal", 0) or 0),
                        "tokenApprox": int(out_stats.get("tokenApprox", 0) or 0),
                        "decisions": int(out_stats.get("decisions", 0) or 0),
                        "highlights": int(out_stats.get("highlights", 0) or 0),
                        "tokens": int(out_stats.get("tokens", 0) or 0),
                        "truncation": {
                            "decisionsDropped": int(truncation.get("decisionsDropped", 0) or 0),
                            "highlightsDropped": int(truncation.get("highlightsDropped", 0) or 0),
                            "tokensDropped": int(truncation.get("tokensDropped", 0) or 0),
                            "charsDropped": int(truncation.get("charsDropped", 0) or 0),
                        },
                    },
                    "metrics": metrics,
                }
            )
    finally:
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)

    payload = {
        "schemaVersion": "byes.ablation.pov_budget.v1",
        "runPackage": str(run_package_resolved),
        "mode": mode,
        "budgets": budgets,
        "rows": rows,
    }
    payload["recommendation"] = _recommend(rows)

    latest_json = out_dir / "latest.json"
    latest_md = out_dir / "latest.md"
    latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest_md.write_text(_render_markdown(payload), encoding="utf-8")

    exit_code = 0
    if fail_on_critical_fn and critical_fn_failed:
        exit_code = 2
    return payload, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run POV context budget ablation and emit latest.json/latest.md.")
    parser.add_argument("--run-package", required=True, help="Run package directory or .zip")
    parser.add_argument("--budgets", default="256,512,1024", help="Comma-separated maxTokensApprox list")
    parser.add_argument("--mode", default="decisions_plus_highlights", choices=["decisions_only", "decisions_plus_highlights", "full"])
    parser.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "byes_pov_ablation"), help="Output directory")
    parser.add_argument("--use-http", default="0", help="1 to call /api/pov/context; 0 to use local module")
    parser.add_argument("--fail-on-critical-fn", default="0", help="1 to return code 2 when any critical_fn>0")
    args = parser.parse_args(argv)

    budgets = _parse_budgets(args.budgets)
    payload, exit_code = run_ablation(
        run_package=Path(args.run_package),
        budgets=budgets,
        mode=str(args.mode),
        out_dir=Path(args.out),
        use_http=_parse_bool01(args.use_http),
        fail_on_critical_fn=_parse_bool01(args.fail_on_critical_fn),
    )
    recommendation = payload.get("recommendation", {})
    print(f"[ablation] runPackage={payload.get('runPackage', '')} mode={payload.get('mode', '')} budgets={payload.get('budgets', [])}")
    print(f"[recommendation] bestMaxTokensApprox={recommendation.get('bestMaxTokensApprox', None)}")
    print(f"[rule] {recommendation.get('rule', '')}")
    print(f"[out] {Path(args.out).resolve() / 'latest.json'}")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
