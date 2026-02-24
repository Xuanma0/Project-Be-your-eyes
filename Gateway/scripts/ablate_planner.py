from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from itertools import product
from pathlib import Path
from typing import Any, Callable

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent


def _parse_csv_list(raw: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for chunk in str(raw or "").split(","):
        text = chunk.strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        values.append(text)
    return values


def _parse_budgets(raw: str) -> list[int]:
    values: list[int] = []
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
        values.append(value)
    if not values:
        raise ValueError("pov-budgets must contain positive integers")
    return values


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


def _extract_metrics(report_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    quality = report_payload.get("quality", {})
    quality = quality if isinstance(quality, dict) else {}
    depth_risk = quality.get("depthRisk", {})
    depth_risk = depth_risk if isinstance(depth_risk, dict) else {}
    critical = depth_risk.get("critical", {})
    critical = critical if isinstance(critical, dict) else {}
    risk_latency = quality.get("riskLatencyMs", {})
    risk_latency = risk_latency if isinstance(risk_latency, dict) else {}

    plan_eval = report_payload.get("planEval", {})
    plan_eval = plan_eval if isinstance(plan_eval, dict) else {}
    plan_latency = plan_eval.get("latencyMs", {})
    plan_latency = plan_latency if isinstance(plan_latency, dict) else {}
    confirm = plan_eval.get("confirm", {})
    confirm = confirm if isinstance(confirm, dict) else {}
    overcautious = plan_eval.get("overcautious", {})
    overcautious = overcautious if isinstance(overcautious, dict) else {}
    guardrails = plan_eval.get("guardrails", {})
    guardrails = guardrails if isinstance(guardrails, dict) else {}

    pov_context = report_payload.get("povContext", {})
    pov_context = pov_context if isinstance(pov_context, dict) else {}
    context_out = pov_context.get("out", {})
    context_out = context_out if isinstance(context_out, dict) else {}

    metrics = {
        "qualityScore": _to_float(quality.get("qualityScore")),
        "critical_fn": _to_int(critical.get("missCriticalCount")),
        "missCriticalCount": _to_int(critical.get("missCriticalCount")),
        "riskLatencyP90": _to_int(risk_latency.get("p90")),
        "plan_latency_p90": _to_int(plan_latency.get("p90")),
        "confirm_timeouts": _to_int(confirm.get("timeouts")) or 0,
        "confirm_requests": _to_int(confirm.get("requests")) or 0,
        "overcautious_rate": _to_float(overcautious.get("rate")),
        "guardrail_override_rate": _to_float(guardrails.get("overrideRate")),
    }
    context = {
        "tokenApprox": _to_int(context_out.get("tokenApprox")) or 0,
        "charsTotal": _to_int(context_out.get("charsTotal")) or 0,
        "decisions": _to_int(context_out.get("decisions")) or 0,
        "highlights": _to_int(context_out.get("highlights")) or 0,
        "tokens": _to_int(context_out.get("tokens")) or 0,
    }
    return context, metrics


def evaluate_setting(
    *,
    run_package: Path,
    provider: str,
    prompt_version: str,
    budget_tokens: int,
    out_dir: Path,
) -> dict[str, Any]:
    safe_name = f"{provider}_{prompt_version}_{budget_tokens}".replace("/", "_")
    report_md = out_dir / f"report_{safe_name}.md"
    report_json = out_dir / f"report_{safe_name}.json"

    env = os.environ.copy()
    env["BYES_PLANNER_PROVIDER"] = str(provider)
    env["BYES_PLANNER_PROMPT_VERSION"] = str(prompt_version)
    env["BYES_PLAN_BUDGET_MAX_TOKENS"] = str(int(budget_tokens))
    env["BYES_PLAN_BUDGET_MAX_CHARS"] = str(min(4000, int(budget_tokens) * 4))

    cmd = [
        sys.executable,
        str(GATEWAY_ROOT / "scripts" / "report_run.py"),
        "--run-package",
        str(run_package),
        "--output",
        str(report_md),
        "--output-json",
        str(report_json),
    ]
    result = subprocess.run(cmd, cwd=GATEWAY_ROOT, env=env, capture_output=True, text=True, check=False)
    row: dict[str, Any] = {
        "provider": str(provider),
        "promptVersion": str(prompt_version),
        "maxTokensApprox": int(budget_tokens),
        "maxChars": int(min(4000, int(budget_tokens) * 4)),
        "context": {
            "tokenApprox": 0,
            "charsTotal": 0,
            "decisions": 0,
            "highlights": 0,
            "tokens": 0,
        },
        "metrics": {
            "qualityScore": None,
            "critical_fn": None,
            "missCriticalCount": None,
            "riskLatencyP90": None,
            "plan_latency_p90": None,
            "confirm_timeouts": None,
            "confirm_requests": None,
            "overcautious_rate": None,
            "guardrail_override_rate": None,
        },
        "notes": "",
        "stdout": result.stdout.strip(),
    }
    if result.returncode != 0:
        row["notes"] = f"report_failed:{result.returncode}"
        return row
    try:
        payload = json.loads(report_json.read_text(encoding="utf-8-sig"))
    except Exception as ex:  # noqa: BLE001
        row["notes"] = f"report_json_parse_failed:{ex}"
        return row
    if not isinstance(payload, dict):
        row["notes"] = "report_json_invalid"
        return row

    context, metrics = _extract_metrics(payload)
    row["context"] = context
    row["metrics"] = metrics
    row["notes"] = "ok"
    return row


def _rank_key(row: dict[str, Any]) -> tuple[float, float, float, int]:
    metrics = row.get("metrics", {})
    metrics = metrics if isinstance(metrics, dict) else {}

    confirm_timeouts = metrics.get("confirm_timeouts")
    plan_latency_p90 = metrics.get("plan_latency_p90")
    quality_score = metrics.get("qualityScore")

    confirm_rank = float(confirm_timeouts) if isinstance(confirm_timeouts, (int, float)) else 1e12
    latency_rank = float(plan_latency_p90) if isinstance(plan_latency_p90, (int, float)) else 1e12
    quality_rank = -float(quality_score) if isinstance(quality_score, (int, float)) else 1e12
    budget = int(row.get("maxTokensApprox", 0) or 0)
    return (confirm_rank, latency_rank, quality_rank, budget)


def recommend_best(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        row
        for row in rows
        if isinstance(row.get("metrics"), dict)
        and isinstance(row["metrics"].get("critical_fn"), int)
        and int(row["metrics"]["critical_fn"]) == 0
    ]
    chosen = eligible if eligible else rows
    chosen_sorted = sorted(chosen, key=_rank_key)
    best = chosen_sorted[0] if chosen_sorted else None
    return {
        "rule": "minimize confirm_timeouts subject to critical_fn==0 then minimize plan_latency_p90 then maximize qualityScore",
        "best": {
            "provider": best.get("provider") if isinstance(best, dict) else None,
            "promptVersion": best.get("promptVersion") if isinstance(best, dict) else None,
            "maxTokensApprox": best.get("maxTokensApprox") if isinstance(best, dict) else None,
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Planner Ablation")
    lines.append("")
    lines.append(f"- runPackage: `{payload.get('runPackage', '')}`")
    lines.append(f"- providers: `{payload.get('providers', [])}`")
    lines.append(f"- promptVersions: `{payload.get('promptVersions', [])}`")
    lines.append(f"- budgets: `{payload.get('povBudgets', [])}`")
    lines.append("")
    lines.append("| provider | prompt | budgetTok | plan_latency_p90 | confirm_timeouts | qualityScore | critical_fn | overcautiousRate | guardrailOverrideRate |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for row in payload.get("rows", []):
        metrics = row.get("metrics", {})
        metrics = metrics if isinstance(metrics, dict) else {}
        lines.append(
            "| {provider} | {prompt} | {budget} | {lat} | {timeouts} | {quality} | {critical} | {overcautious} | {guardrail} |".format(
                provider=row.get("provider"),
                prompt=row.get("promptVersion"),
                budget=row.get("maxTokensApprox"),
                lat=metrics.get("plan_latency_p90"),
                timeouts=metrics.get("confirm_timeouts"),
                quality=metrics.get("qualityScore"),
                critical=metrics.get("critical_fn"),
                overcautious=metrics.get("overcautious_rate"),
                guardrail=metrics.get("guardrail_override_rate"),
            )
        )
    lines.append("")
    recommendation = payload.get("recommendation", {})
    lines.append(f"- recommendation: `{json.dumps(recommendation, ensure_ascii=False)}`")
    return "\n".join(lines) + "\n"


def run_ablation(
    *,
    run_package: Path,
    providers: list[str],
    prompt_versions: list[str],
    budgets: list[int],
    out_dir: Path,
    fail_on_critical_fn: bool,
    evaluator: Callable[..., dict[str, Any]] = evaluate_setting,
) -> tuple[dict[str, Any], int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_package_resolved = run_package.resolve()
    rows: list[dict[str, Any]] = []

    for provider, prompt_version, budget in product(providers, prompt_versions, budgets):
        row = evaluator(
            run_package=run_package_resolved,
            provider=provider,
            prompt_version=prompt_version,
            budget_tokens=int(budget),
            out_dir=out_dir,
        )
        rows.append(row)

    payload = {
        "schemaVersion": "byes.planner.ablation.v1",
        "runPackage": str(run_package_resolved),
        "providers": providers,
        "promptVersions": prompt_versions,
        "povBudgets": budgets,
        "rows": rows,
    }
    payload["recommendation"] = recommend_best(rows)

    latest_json = out_dir / "latest.json"
    latest_md = out_dir / "latest.md"
    latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest_md.write_text(render_markdown(payload), encoding="utf-8")

    exit_code = 0
    if fail_on_critical_fn:
        for row in rows:
            metrics = row.get("metrics", {})
            if not isinstance(metrics, dict):
                continue
            critical_fn = metrics.get("critical_fn")
            if isinstance(critical_fn, int) and critical_fn > 0:
                exit_code = 2
                break
    return payload, exit_code


def _parse_bool01(raw: str | int | bool) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return raw != 0
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Planner ablation sweep across provider/prompt/budget settings.")
    parser.add_argument("--run-package", required=True, help="Run package directory or zip path")
    parser.add_argument("--providers", default="reference,llm", help="Comma-separated providers list")
    parser.add_argument("--prompt-versions", default="v1", help="Comma-separated prompt versions")
    parser.add_argument("--pov-budgets", default="128,256", help="Comma-separated maxTokensApprox values")
    parser.add_argument(
        "--out",
        default=str(Path(tempfile.gettempdir()) / "byes_plan_ablation"),
        help="Output directory (writes latest.json/latest.md)",
    )
    parser.add_argument("--fail-on-critical-fn", default="0", help="Return code 2 if any setting has critical_fn>0")
    args = parser.parse_args(argv)

    providers = _parse_csv_list(args.providers)
    prompt_versions = _parse_csv_list(args.prompt_versions)
    budgets = _parse_budgets(args.pov_budgets)
    if not providers:
        raise ValueError("providers cannot be empty")
    if not prompt_versions:
        raise ValueError("prompt-versions cannot be empty")

    payload, exit_code = run_ablation(
        run_package=Path(args.run_package),
        providers=providers,
        prompt_versions=prompt_versions,
        budgets=budgets,
        out_dir=Path(args.out),
        fail_on_critical_fn=_parse_bool01(args.fail_on_critical_fn),
    )

    recommendation = payload.get("recommendation", {})
    print(
        "[ablation] runPackage={run_pkg} providers={providers} promptVersions={prompts} budgets={budgets}".format(
            run_pkg=payload.get("runPackage", ""),
            providers=payload.get("providers", []),
            prompts=payload.get("promptVersions", []),
            budgets=payload.get("povBudgets", []),
        )
    )
    print(f"[recommendation] {json.dumps(recommendation, ensure_ascii=False)}")
    print(f"[out] {(Path(args.out).resolve() / 'latest.json')}")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
