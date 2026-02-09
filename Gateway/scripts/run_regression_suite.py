from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent
REPO_ROOT = GATEWAY_ROOT.parent
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))

from scripts.report_run import generate_report_outputs, resolve_run_package_input  # noqa: E402


@dataclass
class RunSummary:
    run_id: str
    run_path: str
    scenario_tag: str
    report_md: str
    report_json: str
    quality_score: float | None
    has_ground_truth: bool
    ocr_cer: float | None
    ocr_wer: float | None
    ocr_exact_match_rate: float | None
    depth_risk_f1: float | None
    confirm_timeouts: int
    confirm_missing_response: int
    event_schema_source: str
    event_schema_normalized_events: int
    event_schema_warnings_count: int
    top_findings: list[dict[str, Any]]
    score_delta: float | None = None
    baseline_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.run_id,
            "runPath": self.run_path,
            "scenarioTag": self.scenario_tag,
            "reportMd": self.report_md,
            "reportJson": self.report_json,
            "qualityScore": self.quality_score,
            "hasGroundTruth": self.has_ground_truth,
            "ocr": {
                "cer": self.ocr_cer,
                "wer": self.ocr_wer,
                "exactMatchRate": self.ocr_exact_match_rate,
            },
            "depthRisk": {
                "f1": self.depth_risk_f1,
            },
            "safetyBehavior": {
                "confirmTimeouts": self.confirm_timeouts,
                "confirmMissingResponse": self.confirm_missing_response,
            },
            "eventSchema": {
                "source": self.event_schema_source,
                "normalizedEvents": self.event_schema_normalized_events,
                "warningsCount": self.event_schema_warnings_count,
            },
            "topFindings": self.top_findings,
            "baselineScore": self.baseline_score,
            "scoreDelta": self.score_delta,
        }


def _resolve_input_path(path_text: str, suite_dir: Path) -> Path:
    candidate = Path(path_text)
    if candidate.exists():
        return candidate.resolve()

    candidates = [
        suite_dir / path_text,
        GATEWAY_ROOT / path_text,
        REPO_ROOT / path_text,
        Path.cwd() / path_text,
    ]
    for item in candidates:
        if item.exists():
            return item.resolve()
    return candidate


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object json: {path}")
    return payload


def _collect_baseline_scores(baseline_payload: dict[str, Any]) -> dict[str, float]:
    scores: dict[str, float] = {}
    runs = baseline_payload.get("runs")
    if isinstance(runs, list):
        for row in runs:
            if not isinstance(row, dict):
                continue
            run_id = str(row.get("id", "")).strip()
            score = row.get("qualityScore")
            if not run_id or score is None:
                continue
            try:
                scores[run_id] = float(score)
            except Exception:
                continue
    return scores


def _extract_run_summary(
    run_id: str,
    run_path: Path,
    report_md: Path,
    report_json: Path,
    report_payload: dict[str, Any],
) -> RunSummary:
    quality = report_payload.get("quality")
    quality = quality if isinstance(quality, dict) else {}
    ocr = quality.get("ocr")
    ocr = ocr if isinstance(ocr, dict) else {}
    depth_risk = quality.get("depthRisk")
    depth_risk = depth_risk if isinstance(depth_risk, dict) else {}
    depth_overall = depth_risk.get("overall")
    depth_overall = depth_overall if isinstance(depth_overall, dict) else {}
    safety = quality.get("safetyBehavior")
    safety = safety if isinstance(safety, dict) else {}
    confirm = safety.get("confirm")
    confirm = confirm if isinstance(confirm, dict) else {}
    event_schema = quality.get("eventSchema")
    event_schema = event_schema if isinstance(event_schema, dict) else {}
    top_findings = quality.get("topFindings")
    if not isinstance(top_findings, list):
        top_findings = []

    quality_score = quality.get("qualityScore")
    if quality_score is not None:
        try:
            quality_score = float(quality_score)
        except Exception:
            quality_score = None

    return RunSummary(
        run_id=run_id,
        run_path=str(run_path),
        scenario_tag=str(report_payload.get("scenarioTag", "")),
        report_md=str(report_md),
        report_json=str(report_json),
        quality_score=quality_score,
        has_ground_truth=bool(quality.get("hasGroundTruth")),
        ocr_cer=_try_float(ocr.get("cer")),
        ocr_wer=_try_float(ocr.get("wer")),
        ocr_exact_match_rate=_try_float(ocr.get("exactMatchRate")),
        depth_risk_f1=_try_float(depth_overall.get("f1")),
        confirm_timeouts=int(confirm.get("timeouts", 0) or 0),
        confirm_missing_response=int(confirm.get("missingResponseCount", 0) or 0),
        event_schema_source=str(event_schema.get("source", "")),
        event_schema_normalized_events=int(event_schema.get("normalizedEvents", 0) or 0),
        event_schema_warnings_count=int(event_schema.get("warningsCount", 0) or 0),
        top_findings=[item for item in top_findings if isinstance(item, dict)],
    )


def _try_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _render_markdown(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Regression Suite - {result.get('suiteName', '')}")
    lines.append("")
    lines.append(f"- generatedAtMs: `{result.get('generatedAtMs', 0)}`")
    lines.append(f"- failOnDrop: `{result.get('failOnDrop', False)}`")
    lines.append(f"- baselinePath: `{result.get('baselinePath', '')}`")
    lines.append(f"- exitCode: `{result.get('exitCode', 0)}`")
    lines.append("")
    lines.append("## Runs")
    for run in result.get("runs", []):
        if not isinstance(run, dict):
            continue
        lines.append(
            "- `{id}` score=`{score}` baseline=`{baseline}` delta=`{delta}` confirmTimeouts=`{ct}` schema=`{schema}`".format(
                id=run.get("id", ""),
                score=run.get("qualityScore", None),
                baseline=run.get("baselineScore", None),
                delta=run.get("scoreDelta", None),
                ct=run.get("safetyBehavior", {}).get("confirmTimeouts", 0),
                schema=run.get("eventSchema", {}).get("source", ""),
            )
        )
    failures = result.get("failures", [])
    lines.append("")
    lines.append("## Failures")
    if not failures:
        lines.append("- none")
    else:
        for item in failures:
            lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def run_suite(
    suite_path: Path,
    out_path: Path,
    baseline_path: Path | None = None,
    fail_on_drop: bool = False,
    write_baseline: bool = False,
) -> tuple[dict[str, Any], int]:
    suite = _load_json(suite_path)
    suite_name = str(suite.get("name", suite_path.stem))
    runs_cfg = suite.get("runs")
    if not isinstance(runs_cfg, list) or not runs_cfg:
        raise ValueError("suite.runs must be a non-empty list")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    reports_dir = out_path.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    suite_dir = suite_path.parent

    baseline_scores: dict[str, float] = {}
    if baseline_path is not None and baseline_path.exists():
        baseline_scores = _collect_baseline_scores(_load_json(baseline_path))

    expected = suite.get("expected")
    expected = expected if isinstance(expected, dict) else {}
    min_quality = _try_float(expected.get("minQualityScore"))
    max_confirm_timeouts = expected.get("maxConfirmTimeouts")
    try:
        max_confirm_timeouts = int(max_confirm_timeouts) if max_confirm_timeouts is not None else None
    except Exception:
        max_confirm_timeouts = None

    run_summaries: list[RunSummary] = []
    failures: list[str] = []

    for run_cfg in runs_cfg:
        if not isinstance(run_cfg, dict):
            continue
        run_id = str(run_cfg.get("id", "")).strip()
        run_path_text = str(run_cfg.get("path", "")).strip()
        if not run_id or not run_path_text:
            continue
        run_path = _resolve_input_path(run_path_text, suite_dir)

        ws_jsonl: Path | None = None
        metrics_before: Path | None = None
        metrics_after: Path | None = None
        run_package_summary: dict[str, Any] | None = None
        cleanup_dir: Path | None = None
        try:
            ws_jsonl, metrics_before, metrics_after, run_package_summary, cleanup_dir = resolve_run_package_input(run_path)
            report_md = reports_dir / f"{run_id}.md"
            report_json = reports_dir / f"{run_id}.json"
            _output_md, _output_json, summary_payload = generate_report_outputs(
                ws_jsonl=ws_jsonl,
                output=report_md,
                metrics_url="http://127.0.0.1:8000/metrics",
                metrics_before_path=metrics_before,
                metrics_after_path=metrics_after,
                external_readiness_url=None,
                run_package_summary=run_package_summary,
                output_json=report_json,
            )
            run_summary = _extract_run_summary(run_id, run_path, report_md, report_json, summary_payload)

            baseline_score = baseline_scores.get(run_id)
            run_summary.baseline_score = baseline_score
            if baseline_score is not None and run_summary.quality_score is not None:
                run_summary.score_delta = round(run_summary.quality_score - baseline_score, 3)
            run_summaries.append(run_summary)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{run_id}: report generation failed: {exc}")
        finally:
            if cleanup_dir is not None:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

    for run in run_summaries:
        if min_quality is not None and run.quality_score is not None and run.quality_score < min_quality:
            failures.append(f"{run.run_id}: qualityScore {run.quality_score:.3f} < minQualityScore {min_quality:.3f}")
        if max_confirm_timeouts is not None and run.confirm_timeouts > max_confirm_timeouts:
            failures.append(f"{run.run_id}: confirmTimeouts {run.confirm_timeouts} > maxConfirmTimeouts {max_confirm_timeouts}")
        if fail_on_drop and run.baseline_score is not None and run.quality_score is not None:
            delta = run.quality_score - run.baseline_score
            if delta < -2.0:
                findings = ", ".join(
                    str(item.get("type", "unknown")) for item in run.top_findings[:3] if isinstance(item, dict)
                )
                suffix = f" topFindings={findings}" if findings else ""
                failures.append(
                    f"{run.run_id}: qualityScore drop {run.baseline_score:.3f}->{run.quality_score:.3f} (delta={delta:.3f}){suffix}"
                )

    result = {
        "suiteName": suite_name,
        "suitePath": str(suite_path),
        "generatedAtMs": int(datetime.now(timezone.utc).timestamp() * 1000),
        "failOnDrop": bool(fail_on_drop),
        "baselinePath": str(baseline_path) if baseline_path is not None else "",
        "runs": [run.to_dict() for run in run_summaries],
        "failures": failures,
    }

    if write_baseline and baseline_path is not None:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_payload = {
            "suiteName": suite_name,
            "generatedAtMs": result["generatedAtMs"],
            "runs": [run.to_dict() for run in run_summaries],
        }
        baseline_path.write_text(json.dumps(baseline_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    exit_code = 1 if failures else 0
    result["exitCode"] = exit_code
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path = out_path.with_suffix(".md")
    md_path.write_text(_render_markdown(result), encoding="utf-8")
    return result, exit_code


def _print_summary(result: dict[str, Any]) -> None:
    print(f"[suite] {result.get('suiteName', '')}")
    runs = result.get("runs", [])
    if isinstance(runs, list):
        for row in runs:
            if not isinstance(row, dict):
                continue
            run_id = str(row.get("id", ""))
            score = row.get("qualityScore")
            baseline = row.get("baselineScore")
            delta = row.get("scoreDelta")
            confirm_timeouts = row.get("safetyBehavior", {}).get("confirmTimeouts", 0)
            schema_src = row.get("eventSchema", {}).get("source", "")
            print(
                f"[run] {run_id}: score={score} baseline={baseline} delta={delta} confirmTimeouts={confirm_timeouts} source={schema_src}"
            )
    failures = result.get("failures", [])
    if isinstance(failures, list) and failures:
        print("[failures]")
        for item in failures:
            print(f"- {item}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run BYES regression suite over run packages and compare against baseline.")
    parser.add_argument("--suite", required=True, help="Path to suite JSON file")
    parser.add_argument("--out", default=str(GATEWAY_ROOT / "regression" / "out" / "latest.json"))
    parser.add_argument("--baseline", default=str(GATEWAY_ROOT / "regression" / "baselines" / "baseline.json"))
    parser.add_argument("--fail-on-drop", action="store_true", default=False)
    parser.add_argument("--write-baseline", action="store_true", default=False)
    args = parser.parse_args(argv)

    suite_path = Path(args.suite)
    out_path = Path(args.out)
    baseline_path = Path(args.baseline) if args.baseline else None
    try:
        result, exit_code = run_suite(
            suite_path=suite_path,
            out_path=out_path,
            baseline_path=baseline_path,
            fail_on_drop=bool(args.fail_on_drop),
            write_baseline=bool(args.write_baseline),
        )
        _print_summary(result)
        print(f"[out] {out_path}")
        return exit_code
    except Exception as exc:  # noqa: BLE001
        print(f"run_regression_suite failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
