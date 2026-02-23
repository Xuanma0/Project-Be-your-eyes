from __future__ import annotations

import argparse
import json
import subprocess
import shutil
import sys
import tempfile
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
from scripts.lint_run_package import lint_run_package  # noqa: E402


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
    miss_critical_count: int | None
    depth_risk_delay_p90: int | None
    depth_risk_delay_max: int | None
    risk_latency_p90: int | None
    risk_latency_max: int | None
    seg_f1_50: float | None
    seg_coverage: float | None
    seg_latency_p90: int | None
    depth_absrel: float | None
    depth_rmse: float | None
    depth_delta1: float | None
    depth_coverage: float | None
    depth_latency_p90: int | None
    slam_tracking_rate: float | None
    slam_lost_rate: float | None
    slam_relocalized_count: int | None
    slam_latency_p90: int | None
    confirm_timeouts: int
    confirm_missing_response: int
    event_schema_source: str
    event_schema_normalized_events: int
    event_schema_warnings_count: int
    pov_present: bool
    pov_decisions: int
    pov_token_approx: int
    pov_duration_ms: int | None
    pov_decision_per_min: float | None
    top_findings: list[dict[str, Any]]
    ocr_backend: str | None = None
    risk_backend: str | None = None
    slam_backend: str | None = None
    ocr_model: str | None = None
    risk_model: str | None = None
    slam_model: str | None = None
    ocr_events_present: bool = False
    ocr_payload_schema_ok: bool = False
    ocr_lines: int = 0
    ocr_schema_ok_lines: int = 0
    seg_events_present: bool = False
    seg_payload_schema_ok: bool = False
    seg_lines: int = 0
    seg_schema_ok_lines: int = 0
    depth_events_present: bool = False
    depth_payload_schema_ok: bool = False
    depth_lines: int = 0
    depth_schema_ok_lines: int = 0
    slam_pose_events_present: bool = False
    slam_pose_payload_schema_ok: bool = False
    slam_pose_lines: int = 0
    slam_pose_schema_ok_lines: int = 0
    slam_lost_count: int = 0
    seg_prompt_events_present: bool = False
    seg_prompt_payload_schema_ok: bool = False
    seg_prompt_lines: int = 0
    seg_prompt_schema_ok_lines: int = 0
    seg_prompt_budget_present: bool = False
    seg_prompt_truncation_present: bool = False
    seg_prompt_out_present: bool = False
    seg_prompt_packed_true_count: int = 0
    seg_context_present: bool = False
    seg_context_schema_ok: bool = False
    seg_context_chars: int = 0
    seg_context_segments_out: int = 0
    seg_context_trunc_segments_dropped: int = 0
    slam_context_present: bool = False
    slam_context_schema_ok: bool = False
    slam_ctx_chars_p90: int = 0
    slam_tracking_rate_mean: float = 0.0
    plan_request_events_present: bool = False
    plan_request_schema_ok: bool = False
    plan_request_lines: int = 0
    plan_request_seg_included_count: int = 0
    plan_request_seg_chars_total: int = 0
    plan_context_events_present: bool = False
    plan_context_schema_ok: bool = False
    plan_context_lines: int = 0
    plan_ctx_used_true_count: int = 0
    plan_seg_coverage_p90: float = 0.0
    plan_pov_coverage_p90: float = 0.0
    plan_context_slam_present: bool = False
    plan_context_slam_schema_ok: bool = False
    plan_slam_coverage_p90: float = 0.0
    plan_slam_used_true_count: int = 0
    plan_context_pack_events_present: bool = False
    plan_context_pack_schema_ok: bool = False
    plan_context_pack_lines: int = 0
    plan_ctx_trunc_rate: float = 0.0
    plan_ctx_chars_p90: float = 0.0
    frame_e2e_events_present: bool = False
    frame_e2e_schema_ok: bool = False
    frame_e2e_count: int = 0
    frame_e2e_total_ms_p90: float = 0.0
    frame_e2e_parts_missing_count: int = 0
    frame_input_events_present: bool = False
    frame_input_schema_ok: bool = False
    frame_ack_events_present: bool = False
    frame_ack_schema_ok: bool = False
    frame_user_e2e_events_present: bool = False
    frame_user_e2e_schema_ok: bool = False
    frame_user_e2e_negative_count: int = 0
    frame_user_e2e_duplicate_count: int = 0
    models_present: bool = False
    models_schema_ok: bool = False
    models_missing_required_total: int = 0
    models_enabled_total: int = 0
    score_delta: float | None = None
    baseline_score: float | None = None
    critical_fn_gate_required: bool = False

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
                "missCriticalCount": self.miss_critical_count,
                "delayP90": self.depth_risk_delay_p90,
                "delayMax": self.depth_risk_delay_max,
            },
            "missCriticalCount": self.miss_critical_count,
            "riskLatency": {
                "p90": self.risk_latency_p90,
                "max": self.risk_latency_max,
            },
            "riskLatencyP90": self.risk_latency_p90,
            "riskLatencyMax": self.risk_latency_max,
            "seg": {
                "f1At50": self.seg_f1_50,
                "coverage": self.seg_coverage,
                "latencyP90": self.seg_latency_p90,
            },
            "depth": {
                "absRel": self.depth_absrel,
                "rmse": self.depth_rmse,
                "delta1": self.depth_delta1,
                "coverage": self.depth_coverage,
                "latencyP90": self.depth_latency_p90,
            },
            "slam": {
                "trackingRate": self.slam_tracking_rate,
                "lostRate": self.slam_lost_rate,
                "relocalizedCount": self.slam_relocalized_count,
                "latencyP90": self.slam_latency_p90,
            },
            "segF1At50": self.seg_f1_50,
            "segCoverage": self.seg_coverage,
            "segLatencyP90": self.seg_latency_p90,
            "depthAbsRel": self.depth_absrel,
            "depthRmse": self.depth_rmse,
            "depthDelta1": self.depth_delta1,
            "depthCoverage": self.depth_coverage,
            "depthLatencyP90": self.depth_latency_p90,
            "frameE2E": {
                "eventsPresent": self.frame_e2e_events_present,
                "schemaOk": self.frame_e2e_schema_ok,
                "count": self.frame_e2e_count,
                "totalMsP90": self.frame_e2e_total_ms_p90,
                "partsMissingCount": self.frame_e2e_parts_missing_count,
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
            "pov": {
                "present": self.pov_present,
                "decisions": self.pov_decisions,
                "tokenApprox": self.pov_token_approx,
                "durationMs": self.pov_duration_ms,
                "decisionPerMin": self.pov_decision_per_min,
            },
            "povPresent": self.pov_present,
            "povDecisions": self.pov_decisions,
            "povTokenApprox": self.pov_token_approx,
            "inference": {
                "ocr": {
                    "backend": self.ocr_backend,
                    "model": self.ocr_model,
                },
                "risk": {
                    "backend": self.risk_backend,
                    "model": self.risk_model,
                },
                "slam": {
                    "backend": self.slam_backend,
                    "model": self.slam_model,
                },
            },
            "topFindings": self.top_findings,
            "segLint": {
                "eventsPresent": self.seg_events_present,
                "ocrEventsPresent": self.ocr_events_present,
                "ocrPayloadSchemaOk": self.ocr_payload_schema_ok,
                "ocrLines": self.ocr_lines,
                "ocrSchemaOkLines": self.ocr_schema_ok_lines,
                "payloadSchemaOk": self.seg_payload_schema_ok,
                "segLines": self.seg_lines,
                "segSchemaOkLines": self.seg_schema_ok_lines,
                "depthEventsPresent": self.depth_events_present,
                "depthPayloadSchemaOk": self.depth_payload_schema_ok,
                "depthLines": self.depth_lines,
                "depthSchemaOkLines": self.depth_schema_ok_lines,
                "slamPoseEventsPresent": self.slam_pose_events_present,
                "slamPosePayloadSchemaOk": self.slam_pose_payload_schema_ok,
                "slamPoseLines": self.slam_pose_lines,
                "slamPoseSchemaOkLines": self.slam_pose_schema_ok_lines,
                "slamLostCount": self.slam_lost_count,
                "promptEventsPresent": self.seg_prompt_events_present,
                "promptPayloadSchemaOk": self.seg_prompt_payload_schema_ok,
                "segPromptLines": self.seg_prompt_lines,
                "segPromptSchemaOkLines": self.seg_prompt_schema_ok_lines,
                "segPromptBudgetPresent": self.seg_prompt_budget_present,
                "segPromptTruncationPresent": self.seg_prompt_truncation_present,
                "segPromptOutPresent": self.seg_prompt_out_present,
                "segPromptPackedTrueCount": self.seg_prompt_packed_true_count,
                "segContextPresent": self.seg_context_present,
                "segContextSchemaOk": self.seg_context_schema_ok,
                "segContextChars": self.seg_context_chars,
                "segContextSegmentsOut": self.seg_context_segments_out,
                "segContextTruncSegmentsDropped": self.seg_context_trunc_segments_dropped,
                "slamContextPresent": self.slam_context_present,
                "slamContextSchemaOk": self.slam_context_schema_ok,
                "slamCtxCharsP90": self.slam_ctx_chars_p90,
                "slamTrackingRateMean": self.slam_tracking_rate_mean,
                "planRequestEventsPresent": self.plan_request_events_present,
                "planRequestSchemaOk": self.plan_request_schema_ok,
                "planRequestLines": self.plan_request_lines,
                "planRequestSegIncludedCount": self.plan_request_seg_included_count,
                "planRequestSegCharsTotal": self.plan_request_seg_chars_total,
                "planContextEventsPresent": self.plan_context_events_present,
                "planContextSchemaOk": self.plan_context_schema_ok,
                "planContextLines": self.plan_context_lines,
                "planCtxUsedTrueCount": self.plan_ctx_used_true_count,
                "planSegCoverageP90": self.plan_seg_coverage_p90,
                "planPovCoverageP90": self.plan_pov_coverage_p90,
                "planContextSlamPresent": self.plan_context_slam_present,
                "planContextSlamSchemaOk": self.plan_context_slam_schema_ok,
                "planSlamCoverageP90": self.plan_slam_coverage_p90,
                "planSlamUsedTrueCount": self.plan_slam_used_true_count,
                "planContextPackEventsPresent": self.plan_context_pack_events_present,
                "planContextPackSchemaOk": self.plan_context_pack_schema_ok,
                "planContextPackLines": self.plan_context_pack_lines,
                "planCtxTruncRate": self.plan_ctx_trunc_rate,
                "planCtxCharsP90": self.plan_ctx_chars_p90,
                "frameE2eEventsPresent": self.frame_e2e_events_present,
                "frameE2eSchemaOk": self.frame_e2e_schema_ok,
                "frameE2eCount": self.frame_e2e_count,
                "frameE2eTotalMsP90": self.frame_e2e_total_ms_p90,
                "frameE2ePartsMissingCount": self.frame_e2e_parts_missing_count,
                "frameInputEventsPresent": self.frame_input_events_present,
                "frameInputSchemaOk": self.frame_input_schema_ok,
                "frameAckEventsPresent": self.frame_ack_events_present,
                "frameAckSchemaOk": self.frame_ack_schema_ok,
                "frameUserE2eEventsPresent": self.frame_user_e2e_events_present,
                "frameUserE2eSchemaOk": self.frame_user_e2e_schema_ok,
                "frameUserE2eNegativeCount": self.frame_user_e2e_negative_count,
                "frameUserE2eDuplicateCount": self.frame_user_e2e_duplicate_count,
                "modelsPresent": self.models_present,
                "modelsSchemaOk": self.models_schema_ok,
                "modelsMissingRequiredTotal": self.models_missing_required_total,
                "modelsEnabledTotal": self.models_enabled_total,
            },
            "baselineScore": self.baseline_score,
            "scoreDelta": self.score_delta,
            "criticalFnGateRequired": self.critical_fn_gate_required,
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


def _run_contract_lock_check() -> tuple[bool, str]:
    script = GATEWAY_ROOT / "scripts" / "verify_contracts.py"
    if not script.exists():
        return False, f"verify script not found: {script}"
    result = subprocess.run(
        [sys.executable, str(script), "--check-lock"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    detail = output
    if err:
        detail = f"{detail}\n{err}".strip()
    return result.returncode == 0, detail


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object json: {path}")
    return payload


def _load_manifest_if_any(run_path: Path) -> tuple[Path | None, dict[str, Any] | None]:
    if not run_path.exists() or not run_path.is_dir():
        return None, None
    for name in ("manifest.json", "run_manifest.json"):
        path = run_path / name
        if not path.exists():
            continue
        try:
            payload = _load_json(path)
        except Exception:
            continue
        return path, payload
    return None, None


def _jsonl_has_rows(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    with path.open("r", encoding="utf-8-sig") as fp:
        for raw in fp:
            if raw.strip():
                return True
    return False


def _to_bool01(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _run_pov_ingest_pre_step(run_path: Path, step_cfg: dict[str, Any]) -> None:
    _manifest_path, manifest = _load_manifest_if_any(run_path)
    manifest = manifest if isinstance(manifest, dict) else {}
    events_rel = str(step_cfg.get("eventsV1Jsonl", "")).strip() or str(manifest.get("eventsV1Jsonl", "")).strip() or "events/events_v1.jsonl"
    events_path = run_path / events_rel
    if _jsonl_has_rows(events_path):
        return

    pov_rel = str(step_cfg.get("povIrJson", "")).strip() or str(manifest.get("povIrJson", "")).strip() or "pov/pov_ir_v1.json"
    pov_path = run_path / pov_rel
    if not pov_path.exists():
        raise FileNotFoundError(f"pov ir not found for ingest: {pov_path}")

    strict = "1" if _to_bool01(step_cfg.get("strict"), True) else "0"
    script = GATEWAY_ROOT / "scripts" / "ingest_pov_ir.py"
    result = subprocess.run(
        [sys.executable, str(script), "--run-package", str(run_path), "--pov-ir", str(pov_path), "--strict", strict],
        cwd=GATEWAY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = f"pov ingest failed rc={result.returncode}; stdout={result.stdout.strip()} stderr={result.stderr.strip()}".strip()
        raise RuntimeError(detail)


def _run_pre_steps(run_cfg: dict[str, Any], run_path: Path) -> None:
    if not run_path.exists() or not run_path.is_dir():
        return
    explicit_ingest = False
    steps = run_cfg.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, str):
                step_type = step.strip().lower()
                step_cfg: dict[str, Any] = {}
            elif isinstance(step, dict):
                step_type = str(step.get("type", step.get("name", ""))).strip().lower()
                step_cfg = step
            else:
                continue
            if step_type in {"ingest_pov_ir", "pov_ingest", "ingest-pov-ir"}:
                explicit_ingest = True
                _run_pov_ingest_pre_step(run_path, step_cfg)

    if explicit_ingest or not _to_bool01(run_cfg.get("autoIngestPovIr"), True):
        return
    _manifest_path, manifest = _load_manifest_if_any(run_path)
    if not isinstance(manifest, dict):
        return
    if str(manifest.get("povIrJson", "")).strip():
        _run_pov_ingest_pre_step(run_path, {})


def _has_ingest_step(run_cfg: dict[str, Any]) -> bool:
    steps = run_cfg.get("steps")
    if not isinstance(steps, list):
        return False
    for step in steps:
        if isinstance(step, str):
            step_type = step.strip().lower()
        elif isinstance(step, dict):
            step_type = str(step.get("type", step.get("name", ""))).strip().lower()
        else:
            continue
        if step_type in {"ingest_pov_ir", "pov_ingest", "ingest-pov-ir"}:
            return True
    return False


def _requires_mutating_pre_steps(run_cfg: dict[str, Any], run_path: Path) -> bool:
    if not run_path.exists() or not run_path.is_dir():
        return False
    if _has_ingest_step(run_cfg):
        return True
    if not _to_bool01(run_cfg.get("autoIngestPovIr"), True):
        return False
    _manifest_path, manifest = _load_manifest_if_any(run_path)
    if not isinstance(manifest, dict):
        return False
    pov_rel = str(manifest.get("povIrJson", "")).strip()
    if not pov_rel:
        return False
    events_rel = str(manifest.get("eventsV1Jsonl", "")).strip() or "events/events_v1.jsonl"
    return not _jsonl_has_rows(run_path / events_rel)


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


def _collect_baseline_expectations(baseline_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    expectations: dict[str, dict[str, Any]] = {}
    runs = baseline_payload.get("runs")
    if not isinstance(runs, list):
        return expectations
    for row in runs:
        if not isinstance(row, dict):
            continue
        run_id = str(row.get("id", "")).strip()
        if not run_id:
            continue
        item: dict[str, Any] = {}
        min_quality = _try_float(row.get("minQualityScore"))
        if min_quality is not None:
            item["minQualityScore"] = float(min_quality)
        if "criticalFnMustBeZero" in row:
            item["criticalFnMustBeZero"] = bool(row.get("criticalFnMustBeZero"))
        if "requireCriticalFnZero" in row:
            item["criticalFnMustBeZero"] = bool(row.get("requireCriticalFnZero"))
        if item:
            expectations[run_id] = item
    return expectations


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
    depth_critical = depth_risk.get("critical")
    depth_critical = depth_critical if isinstance(depth_critical, dict) else {}
    depth_delay = depth_risk.get("detectionDelayFrames")
    depth_delay = depth_delay if isinstance(depth_delay, dict) else {}
    risk_latency = quality.get("riskLatencyMs")
    risk_latency = risk_latency if isinstance(risk_latency, dict) else {}
    seg = quality.get("seg")
    seg = seg if isinstance(seg, dict) else {}
    seg_latency = seg.get("latencyMs")
    seg_latency = seg_latency if isinstance(seg_latency, dict) else {}
    depth = quality.get("depth")
    depth = depth if isinstance(depth, dict) else {}
    depth_latency = depth.get("latencyMs")
    depth_latency = depth_latency if isinstance(depth_latency, dict) else {}
    slam = quality.get("slam")
    slam = slam if isinstance(slam, dict) else {}
    slam_tracking = slam.get("tracking")
    slam_tracking = slam_tracking if isinstance(slam_tracking, dict) else {}
    slam_latency = slam.get("latencyMs")
    slam_latency = slam_latency if isinstance(slam_latency, dict) else {}
    safety = quality.get("safetyBehavior")
    safety = safety if isinstance(safety, dict) else {}
    confirm = safety.get("confirm")
    confirm = confirm if isinstance(confirm, dict) else {}
    event_schema = quality.get("eventSchema")
    event_schema = event_schema if isinstance(event_schema, dict) else {}
    pov = report_payload.get("pov")
    pov = pov if isinstance(pov, dict) else {}
    pov_counts = pov.get("counts")
    pov_counts = pov_counts if isinstance(pov_counts, dict) else {}
    pov_time = pov.get("time")
    pov_time = pov_time if isinstance(pov_time, dict) else {}
    pov_budget = pov.get("budget")
    pov_budget = pov_budget if isinstance(pov_budget, dict) else {}
    inference = report_payload.get("inference")
    inference = inference if isinstance(inference, dict) else {}
    inference_ocr = inference.get("ocr")
    inference_ocr = inference_ocr if isinstance(inference_ocr, dict) else {}
    inference_risk = inference.get("risk")
    inference_risk = inference_risk if isinstance(inference_risk, dict) else {}
    inference_slam = inference.get("slam")
    inference_slam = inference_slam if isinstance(inference_slam, dict) else {}
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
        miss_critical_count=_try_int(depth_critical.get("missCriticalCount")),
        depth_risk_delay_p90=_try_int(depth_delay.get("p90")),
        depth_risk_delay_max=_try_int(depth_delay.get("max")),
        risk_latency_p90=_try_int(risk_latency.get("p90")),
        risk_latency_max=_try_int(risk_latency.get("max")),
        seg_f1_50=_try_float(seg.get("f1At50")),
        seg_coverage=_try_float(seg.get("coverage")),
        seg_latency_p90=_try_int(seg_latency.get("p90")),
        depth_absrel=_try_float(depth.get("absRel")),
        depth_rmse=_try_float(depth.get("rmse")),
        depth_delta1=_try_float(depth.get("delta1")),
        depth_coverage=_try_float(depth.get("coverage")),
        depth_latency_p90=_try_int(depth_latency.get("p90")),
        slam_tracking_rate=_try_float(slam_tracking.get("trackingRate")),
        slam_lost_rate=_try_float(slam_tracking.get("lostRate")),
        slam_relocalized_count=_try_int(slam_tracking.get("relocalizedCount")),
        slam_latency_p90=_try_int(slam_latency.get("p90")),
        confirm_timeouts=int(confirm.get("timeouts", 0) or 0),
        confirm_missing_response=int(confirm.get("missingResponseCount", 0) or 0),
        event_schema_source=str(event_schema.get("source", "")),
        event_schema_normalized_events=int(event_schema.get("normalizedEvents", 0) or 0),
        event_schema_warnings_count=int(event_schema.get("warningsCount", 0) or 0),
        pov_present=bool(pov.get("present")),
        pov_decisions=int(pov_counts.get("decisions", 0) or 0),
        pov_token_approx=int(pov_budget.get("tokenApprox", 0) or 0),
        pov_duration_ms=_try_int(pov_time.get("durationMs")),
        pov_decision_per_min=_try_float(pov_time.get("decisionPerMin")),
        ocr_backend=str(inference_ocr.get("backend", "")).strip() or None,
        risk_backend=str(inference_risk.get("backend", "")).strip() or None,
        slam_backend=str(inference_slam.get("backend", "")).strip() or None,
        ocr_model=str(inference_ocr.get("model", "")).strip() or None,
        risk_model=str(inference_risk.get("model", "")).strip() or None,
        slam_model=str(inference_slam.get("model", "")).strip() or None,
        top_findings=[item for item in top_findings if isinstance(item, dict)],
    )


def _try_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _try_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _render_markdown(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Regression Suite - {result.get('suiteName', '')}")
    lines.append("")
    lines.append(f"- generatedAtMs: `{result.get('generatedAtMs', 0)}`")
    lines.append(f"- failOnDrop: `{result.get('failOnDrop', False)}`")
    lines.append(f"- failOnCriticalFn: `{result.get('failOnCriticalFn', True)}`")
    lines.append(f"- baselinePath: `{result.get('baselinePath', '')}`")
    lines.append(f"- exitCode: `{result.get('exitCode', 0)}`")
    lines.append("")
    lines.append("## Runs")
    for run in result.get("runs", []):
        if not isinstance(run, dict):
            continue
        lines.append(
            "- `{id}` score=`{score}` baseline=`{baseline}` delta=`{delta}` confirmTimeouts=`{ct}` criticalFn=`{cfn}` riskDelayMax=`{dmax}` riskLatencyP90=`{rlp90}` riskLatencyMax=`{rlmax}` segF1@0.5=`{seg_f1}` segCoverage=`{seg_cov}` segLatencyP90=`{seg_p90}` depthAbsRel=`{depth_absrel}` depthDelta1=`{depth_delta1}` depthCoverage=`{depth_cov}` depthLatencyP90=`{depth_p90}` slamTrackingRate=`{slam_track}` slamLostRate=`{slam_lost}` slamLatencyP90=`{slam_p90}` segCtxPresent=`{seg_ctx_present}` segCtxSchemaOk=`{seg_ctx_schema_ok}` segCtxChars=`{seg_ctx_chars}` slamCtxPresent=`{slam_ctx_present}` slamCtxSchemaOk=`{slam_ctx_schema_ok}` slamCtxChars=`{slam_ctx_chars}` slamTrackRate=`{slam_track_rate}` povPresent=`{pov_present}` povDecisions=`{pov_decisions}` schema=`{schema}`".format(
                id=run.get("id", ""),
                score=run.get("qualityScore", None),
                baseline=run.get("baselineScore", None),
                delta=run.get("scoreDelta", None),
                ct=run.get("safetyBehavior", {}).get("confirmTimeouts", 0),
                cfn=run.get("depthRisk", {}).get("missCriticalCount", None),
                dmax=run.get("depthRisk", {}).get("delayMax", None),
                rlp90=run.get("riskLatency", {}).get("p90", None),
                rlmax=run.get("riskLatency", {}).get("max", None),
                seg_f1=run.get("seg", {}).get("f1At50", None),
                seg_cov=run.get("seg", {}).get("coverage", None),
                seg_p90=run.get("seg", {}).get("latencyP90", None),
                depth_absrel=run.get("depth", {}).get("absRel", None),
                depth_delta1=run.get("depth", {}).get("delta1", None),
                depth_cov=run.get("depth", {}).get("coverage", None),
                depth_p90=run.get("depth", {}).get("latencyP90", None),
                slam_track=run.get("slam", {}).get("trackingRate", None),
                slam_lost=run.get("slam", {}).get("lostRate", None),
                slam_p90=run.get("slam", {}).get("latencyP90", None),
                seg_ctx_present=run.get("segLint", {}).get("segContextPresent", False),
                seg_ctx_schema_ok=run.get("segLint", {}).get("segContextSchemaOk", False),
                seg_ctx_chars=run.get("segLint", {}).get("segContextChars", 0),
                slam_ctx_present=run.get("segLint", {}).get("slamContextPresent", False),
                slam_ctx_schema_ok=run.get("segLint", {}).get("slamContextSchemaOk", False),
                slam_ctx_chars=run.get("segLint", {}).get("slamCtxCharsP90", 0),
                slam_track_rate=run.get("segLint", {}).get("slamTrackingRateMean", 0.0),
                pov_present=run.get("pov", {}).get("present", False),
                pov_decisions=run.get("pov", {}).get("decisions", 0),
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
    fail_on_critical_fn: bool = True,
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
    baseline_expectations: dict[str, dict[str, Any]] = {}
    if baseline_path is not None and baseline_path.exists():
        baseline_payload = _load_json(baseline_path)
        baseline_scores = _collect_baseline_scores(baseline_payload)
        baseline_expectations = _collect_baseline_expectations(baseline_payload)

    expected = suite.get("expected")
    expected = expected if isinstance(expected, dict) else {}
    min_quality = _try_float(expected.get("minQualityScore"))
    max_confirm_timeouts = expected.get("maxConfirmTimeouts")
    try:
        max_confirm_timeouts = int(max_confirm_timeouts) if max_confirm_timeouts is not None else None
    except Exception:
        max_confirm_timeouts = None
    max_risk_delay = expected.get("maxRiskDelay")
    try:
        max_risk_delay = int(max_risk_delay) if max_risk_delay is not None else None
    except Exception:
        max_risk_delay = None
    expected_require_pov_present = _to_bool01(expected.get("requirePovPresent"), False)
    expected_min_pov_decisions = _try_int(expected.get("minPovDecisions"))
    if suite_name.strip().lower() == "contract":
        if "requirePovPresent" not in expected:
            expected_require_pov_present = True
        if expected_min_pov_decisions is None:
            expected_min_pov_decisions = 2

    run_summaries: list[RunSummary] = []
    run_require_critical_fn: dict[str, bool] = {}
    run_min_quality_override: dict[str, float | None] = {}
    run_require_pov_present: dict[str, bool] = {}
    run_min_pov_decisions_override: dict[str, int | None] = {}
    run_require_ocr_events_present: dict[str, bool] = {}
    run_require_ocr_payload_schema_ok: dict[str, bool] = {}
    run_require_seg_events_present: dict[str, bool] = {}
    run_require_seg_payload_schema_ok: dict[str, bool] = {}
    run_require_depth_events_present: dict[str, bool] = {}
    run_require_depth_payload_schema_ok: dict[str, bool] = {}
    run_require_slam_pose_events_present: dict[str, bool] = {}
    run_require_slam_pose_payload_schema_ok: dict[str, bool] = {}
    run_require_seg_prompt_events_present: dict[str, bool] = {}
    run_require_seg_prompt_payload_schema_ok: dict[str, bool] = {}
    run_require_seg_prompt_budget_present: dict[str, bool] = {}
    run_require_seg_prompt_truncation_present: dict[str, bool] = {}
    run_require_seg_prompt_packed: dict[str, bool] = {}
    run_require_seg_context_present: dict[str, bool] = {}
    run_require_seg_context_schema_ok: dict[str, bool] = {}
    run_require_slam_context_present: dict[str, bool] = {}
    run_require_slam_context_schema_ok: dict[str, bool] = {}
    run_require_plan_request_events_present: dict[str, bool] = {}
    run_require_plan_request_schema_ok: dict[str, bool] = {}
    run_require_plan_context_events_present: dict[str, bool] = {}
    run_require_plan_context_schema_ok: dict[str, bool] = {}
    run_require_plan_context_slam_present: dict[str, bool] = {}
    run_require_plan_context_slam_schema_ok: dict[str, bool] = {}
    run_require_plan_context_pack_events_present: dict[str, bool] = {}
    run_require_plan_context_pack_schema_ok: dict[str, bool] = {}
    run_require_frame_e2e_events_present: dict[str, bool] = {}
    run_require_frame_e2e_schema_ok: dict[str, bool] = {}
    run_require_frame_input_events_present: dict[str, bool] = {}
    run_require_frame_input_schema_ok: dict[str, bool] = {}
    run_require_frame_ack_events_present: dict[str, bool] = {}
    run_require_frame_ack_schema_ok: dict[str, bool] = {}
    run_require_frame_user_e2e_events_present: dict[str, bool] = {}
    run_require_frame_user_e2e_schema_ok: dict[str, bool] = {}
    run_require_models_present: dict[str, bool] = {}
    run_require_models_missing_required_zero: dict[str, bool] = {}
    failures: list[str] = []
    contract_lock_ok: bool | None = None
    contract_lock_detail = ""

    for run_cfg in runs_cfg:
        if not isinstance(run_cfg, dict):
            continue
        run_id = str(run_cfg.get("id", "")).strip()
        run_path_text = str(run_cfg.get("path", "")).strip()
        if not run_path_text:
            run_path_text = str(run_cfg.get("runPackage", "")).strip()
        if not run_id or not run_path_text:
            continue
        run_require_critical_fn[run_id] = bool(run_cfg.get("requireCriticalFnZero", False))
        run_min_quality_override[run_id] = _try_float(run_cfg.get("minQualityScore"))
        run_require_pov_present[run_id] = _to_bool01(run_cfg.get("requirePovPresent"), False)
        run_min_pov_decisions_override[run_id] = _try_int(run_cfg.get("minPovDecisions"))
        run_require_ocr_events_present[run_id] = _to_bool01(run_cfg.get("requireOcrEventsPresent"), False)
        run_require_ocr_payload_schema_ok[run_id] = _to_bool01(run_cfg.get("requireOcrPayloadSchemaOk"), False)
        run_require_seg_events_present[run_id] = _to_bool01(run_cfg.get("requireSegEventsPresent"), False)
        run_require_seg_payload_schema_ok[run_id] = _to_bool01(run_cfg.get("requireSegPayloadSchemaOk"), False)
        run_require_depth_events_present[run_id] = _to_bool01(run_cfg.get("requireDepthEventsPresent"), False)
        run_require_depth_payload_schema_ok[run_id] = _to_bool01(run_cfg.get("requireDepthPayloadSchemaOk"), False)
        run_require_slam_pose_events_present[run_id] = _to_bool01(run_cfg.get("requireSlamPoseEventsPresent"), False)
        run_require_slam_pose_payload_schema_ok[run_id] = _to_bool01(
            run_cfg.get("requireSlamPosePayloadSchemaOk"),
            False,
        )
        run_require_seg_prompt_events_present[run_id] = _to_bool01(run_cfg.get("requireSegPromptEventsPresent"), False)
        run_require_seg_prompt_payload_schema_ok[run_id] = _to_bool01(run_cfg.get("requireSegPromptPayloadSchemaOk"), False)
        run_require_seg_prompt_budget_present[run_id] = _to_bool01(run_cfg.get("requireSegPromptBudgetPresent"), False)
        run_require_seg_prompt_truncation_present[run_id] = _to_bool01(
            run_cfg.get("requireSegPromptTruncationPresent"),
            False,
        )
        run_require_seg_prompt_packed[run_id] = _to_bool01(run_cfg.get("requireSegPromptPacked"), False)
        run_require_seg_context_present[run_id] = _to_bool01(run_cfg.get("requireSegContextPresent"), False)
        run_require_seg_context_schema_ok[run_id] = _to_bool01(run_cfg.get("requireSegContextSchemaOk"), False)
        run_require_slam_context_present[run_id] = _to_bool01(run_cfg.get("requireSlamContextPresent"), False)
        run_require_slam_context_schema_ok[run_id] = _to_bool01(
            run_cfg.get("requireSlamContextSchemaOk"),
            False,
        )
        run_require_plan_request_events_present[run_id] = _to_bool01(run_cfg.get("requirePlanRequestEventsPresent"), False)
        run_require_plan_request_schema_ok[run_id] = _to_bool01(run_cfg.get("requirePlanRequestSchemaOk"), False)
        run_require_plan_context_events_present[run_id] = _to_bool01(run_cfg.get("requirePlanContextEventsPresent"), False)
        run_require_plan_context_schema_ok[run_id] = _to_bool01(run_cfg.get("requirePlanContextSchemaOk"), False)
        run_require_plan_context_slam_present[run_id] = _to_bool01(
            run_cfg.get("requirePlanContextSlamPresent"),
            False,
        )
        run_require_plan_context_slam_schema_ok[run_id] = _to_bool01(
            run_cfg.get("requirePlanContextSlamSchemaOk"),
            False,
        )
        run_require_plan_context_pack_events_present[run_id] = _to_bool01(
            run_cfg.get("requirePlanContextPackEventsPresent"),
            False,
        )
        run_require_plan_context_pack_schema_ok[run_id] = _to_bool01(
            run_cfg.get("requirePlanContextPackSchemaOk"),
            False,
        )
        run_require_frame_e2e_events_present[run_id] = _to_bool01(run_cfg.get("requireFrameE2eEventsPresent"), False)
        run_require_frame_e2e_schema_ok[run_id] = _to_bool01(run_cfg.get("requireFrameE2eSchemaOk"), False)
        run_require_frame_input_events_present[run_id] = _to_bool01(run_cfg.get("requireFrameInputEventsPresent"), False)
        run_require_frame_input_schema_ok[run_id] = _to_bool01(run_cfg.get("requireFrameInputSchemaOk"), False)
        run_require_frame_ack_events_present[run_id] = _to_bool01(run_cfg.get("requireFrameAckEventsPresent"), False)
        run_require_frame_ack_schema_ok[run_id] = _to_bool01(run_cfg.get("requireFrameAckSchemaOk"), False)
        run_require_frame_user_e2e_events_present[run_id] = _to_bool01(
            run_cfg.get("requireFrameUserE2eEventsPresent"),
            False,
        )
        run_require_frame_user_e2e_schema_ok[run_id] = _to_bool01(
            run_cfg.get("requireFrameUserE2eSchemaOk"),
            False,
        )
        run_require_models_present[run_id] = _to_bool01(run_cfg.get("requireModelsPresent"), False)
        run_require_models_missing_required_zero[run_id] = _to_bool01(
            run_cfg.get("requireModelsMissingRequiredZero"),
            False,
        )
        run_path = _resolve_input_path(run_path_text, suite_dir)

        ws_jsonl: Path | None = None
        metrics_before: Path | None = None
        metrics_after: Path | None = None
        run_package_summary: dict[str, Any] | None = None
        cleanup_dir: Path | None = None
        pre_step_temp_dir: Path | None = None
        run_input_path = run_path
        try:
            if _requires_mutating_pre_steps(run_cfg, run_path):
                pre_step_temp_dir = Path(tempfile.mkdtemp(prefix="reg_runpkg_"))
                run_input_path = pre_step_temp_dir / run_path.name
                shutil.copytree(run_path, run_input_path)
            _run_pre_steps(run_cfg, run_input_path)
            ws_jsonl, metrics_before, metrics_after, run_package_summary, cleanup_dir = resolve_run_package_input(run_input_path)
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
            try:
                _lint_code, lint_summary = lint_run_package(run_input_path, strict=False, quiet=True)
                if isinstance(lint_summary, dict):
                    run_summary.ocr_events_present = bool(lint_summary.get("ocrEventsPresent", 0))
                    run_summary.ocr_payload_schema_ok = bool(lint_summary.get("ocrPayloadSchemaOk", 0))
                    run_summary.ocr_lines = int(lint_summary.get("ocrLines", 0) or 0)
                    run_summary.ocr_schema_ok_lines = int(lint_summary.get("ocrSchemaOk", 0) or 0)
                    run_summary.seg_events_present = bool(lint_summary.get("segEventsPresent", 0))
                    run_summary.seg_payload_schema_ok = bool(lint_summary.get("segPayloadSchemaOk", 0))
                    run_summary.seg_lines = int(lint_summary.get("segLines", 0) or 0)
                    run_summary.seg_schema_ok_lines = int(lint_summary.get("segSchemaOk", 0) or 0)
                    run_summary.depth_events_present = bool(lint_summary.get("depthEventsPresent", 0))
                    run_summary.depth_payload_schema_ok = bool(lint_summary.get("depthPayloadSchemaOk", 0))
                    run_summary.depth_lines = int(lint_summary.get("depthLines", 0) or 0)
                    run_summary.depth_schema_ok_lines = int(lint_summary.get("depthSchemaOk", 0) or 0)
                    run_summary.slam_pose_events_present = bool(lint_summary.get("slamPoseEventsPresent", 0))
                    run_summary.slam_pose_payload_schema_ok = bool(lint_summary.get("slamPosePayloadSchemaOk", 0))
                    run_summary.slam_pose_lines = int(lint_summary.get("slamPoseLines", 0) or 0)
                    run_summary.slam_pose_schema_ok_lines = int(lint_summary.get("slamPoseSchemaOk", 0) or 0)
                    run_summary.slam_lost_count = int(lint_summary.get("slamLostCount", 0) or 0)
                    run_summary.seg_prompt_events_present = bool(lint_summary.get("segPromptEventsPresent", 0))
                    run_summary.seg_prompt_payload_schema_ok = bool(lint_summary.get("segPromptPayloadSchemaOk", 0))
                    run_summary.seg_prompt_lines = int(lint_summary.get("segPromptLines", 0) or 0)
                    run_summary.seg_prompt_schema_ok_lines = int(lint_summary.get("segPromptSchemaOk", 0) or 0)
                    run_summary.seg_prompt_budget_present = bool(lint_summary.get("segPromptBudgetPresent", 0))
                    run_summary.seg_prompt_truncation_present = bool(lint_summary.get("segPromptTruncationPresent", 0))
                    run_summary.seg_prompt_out_present = bool(lint_summary.get("segPromptOutPresent", 0))
                    run_summary.seg_prompt_packed_true_count = int(lint_summary.get("segPromptPackedTrueCount", 0) or 0)
                    run_summary.seg_context_present = bool(lint_summary.get("segContextPresent", 0))
                    run_summary.seg_context_schema_ok = bool(lint_summary.get("segContextSchemaOk", 0))
                    run_summary.seg_context_chars = int(lint_summary.get("segContextChars", 0) or 0)
                    run_summary.seg_context_segments_out = int(lint_summary.get("segContextSegmentsOut", 0) or 0)
                    run_summary.seg_context_trunc_segments_dropped = int(
                        lint_summary.get("segContextTruncSegmentsDropped", 0) or 0
                    )
                    run_summary.slam_context_present = bool(lint_summary.get("slamContextPresent", 0))
                    run_summary.slam_context_schema_ok = bool(lint_summary.get("slamContextSchemaOk", 0))
                    run_summary.slam_ctx_chars_p90 = int(lint_summary.get("slamCtxCharsP90", 0) or 0)
                    run_summary.slam_tracking_rate_mean = float(lint_summary.get("slamTrackingRateMean", 0.0) or 0.0)
                    run_summary.plan_request_events_present = bool(lint_summary.get("planRequestEventsPresent", 0))
                    run_summary.plan_request_schema_ok = bool(lint_summary.get("planRequestSchemaOk", 0))
                    run_summary.plan_request_lines = int(lint_summary.get("planRequestLines", 0) or 0)
                    run_summary.plan_request_seg_included_count = int(lint_summary.get("planRequestSegIncludedCount", 0) or 0)
                    run_summary.plan_request_seg_chars_total = int(lint_summary.get("planRequestSegCharsTotal", 0) or 0)
                    run_summary.plan_context_events_present = bool(lint_summary.get("planContextEventsPresent", 0))
                    run_summary.plan_context_schema_ok = bool(lint_summary.get("planContextSchemaOk", 0))
                    run_summary.plan_context_lines = int(lint_summary.get("planContextLines", 0) or 0)
                    run_summary.plan_ctx_used_true_count = int(lint_summary.get("planCtxUsedTrueCount", 0) or 0)
                    run_summary.plan_seg_coverage_p90 = float(lint_summary.get("planSegCoverageP90", 0.0) or 0.0)
                    run_summary.plan_pov_coverage_p90 = float(lint_summary.get("planPovCoverageP90", 0.0) or 0.0)
                    run_summary.plan_context_slam_present = bool(lint_summary.get("planContextSlamPresent", 0))
                    run_summary.plan_context_slam_schema_ok = bool(lint_summary.get("planContextSlamSchemaOk", 0))
                    run_summary.plan_slam_coverage_p90 = float(lint_summary.get("planSlamCoverageP90", 0.0) or 0.0)
                    run_summary.plan_slam_used_true_count = int(lint_summary.get("planSlamUsedTrueCount", 0) or 0)
                    run_summary.plan_context_pack_events_present = bool(lint_summary.get("planContextPackPresent", 0))
                    run_summary.plan_context_pack_schema_ok = bool(lint_summary.get("planContextPackSchemaOk", 0))
                    run_summary.plan_context_pack_lines = int(lint_summary.get("planContextPackLines", 0) or 0)
                    run_summary.plan_ctx_trunc_rate = float(lint_summary.get("planCtxTruncRate", 0.0) or 0.0)
                    run_summary.plan_ctx_chars_p90 = float(lint_summary.get("planCtxCharsP90", 0.0) or 0.0)
                    run_summary.frame_e2e_events_present = bool(lint_summary.get("frameE2eEventsPresent", 0))
                    run_summary.frame_e2e_schema_ok = bool(lint_summary.get("frameE2eSchemaOk", 0))
                    run_summary.frame_e2e_count = int(lint_summary.get("frameE2eCount", 0) or 0)
                    run_summary.frame_e2e_total_ms_p90 = float(lint_summary.get("frameE2eTotalMsP90", 0.0) or 0.0)
                    run_summary.frame_e2e_parts_missing_count = int(
                        lint_summary.get("frameE2ePartsMissingCount", 0) or 0
                    )
                    run_summary.frame_input_events_present = bool(lint_summary.get("frameInputEventsPresent", 0))
                    run_summary.frame_input_schema_ok = bool(lint_summary.get("frameInputSchemaOk", 0))
                    run_summary.frame_ack_events_present = bool(lint_summary.get("frameAckEventsPresent", 0))
                    run_summary.frame_ack_schema_ok = bool(lint_summary.get("frameAckSchemaOk", 0))
                    run_summary.frame_user_e2e_events_present = bool(lint_summary.get("frameUserE2eEventsPresent", 0))
                    run_summary.frame_user_e2e_schema_ok = bool(lint_summary.get("frameUserE2eSchemaOk", 0))
                    run_summary.frame_user_e2e_negative_count = int(
                        lint_summary.get("frameUserE2eNegativeCount", 0) or 0
                    )
                    run_summary.frame_user_e2e_duplicate_count = int(
                        lint_summary.get("frameUserE2eDuplicateCount", 0) or 0
                    )
                    run_summary.models_present = bool(lint_summary.get("modelsPresent", 0))
                    run_summary.models_schema_ok = bool(lint_summary.get("modelsSchemaOk", 0))
                    run_summary.models_missing_required_total = int(
                        lint_summary.get("modelsMissingRequiredTotal", 0) or 0
                    )
                    run_summary.models_enabled_total = int(lint_summary.get("modelsEnabledTotal", 0) or 0)
            except Exception:
                # Lint stats are best-effort; report generation should remain authoritative.
                pass

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
            if pre_step_temp_dir is not None:
                shutil.rmtree(pre_step_temp_dir, ignore_errors=True)

    for run in run_summaries:
        baseline_expect = baseline_expectations.get(run.run_id, {})
        effective_min_quality = run_min_quality_override.get(run.run_id)
        if effective_min_quality is None:
            baseline_min_quality = _try_float(baseline_expect.get("minQualityScore"))
            effective_min_quality = baseline_min_quality if baseline_min_quality is not None else min_quality
        if effective_min_quality is not None and run.quality_score is not None and run.quality_score < effective_min_quality:
            failures.append(
                f"{run.run_id}: qualityScore {run.quality_score:.3f} < minQualityScore {effective_min_quality:.3f}"
            )
        if max_confirm_timeouts is not None and run.confirm_timeouts > max_confirm_timeouts:
            failures.append(f"{run.run_id}: confirmTimeouts {run.confirm_timeouts} > maxConfirmTimeouts {max_confirm_timeouts}")
        if max_risk_delay is not None and run.depth_risk_delay_max is not None and run.depth_risk_delay_max > max_risk_delay:
            failures.append(f"{run.run_id}: riskDelayMax {run.depth_risk_delay_max} > maxRiskDelay {max_risk_delay}")
        baseline_require_critical = bool(baseline_expect.get("criticalFnMustBeZero", False))
        require_critical_fn_zero = bool(fail_on_critical_fn) or run_require_critical_fn.get(run.run_id, False) or baseline_require_critical
        run.critical_fn_gate_required = require_critical_fn_zero
        if require_critical_fn_zero and int(run.miss_critical_count or 0) > 0:
            failures.append(f"{run.run_id}: missCriticalCount {int(run.miss_critical_count or 0)} > 0")
        require_pov_present = run_require_pov_present.get(run.run_id, False) or expected_require_pov_present
        if require_pov_present and not bool(run.pov_present):
            failures.append(f"{run.run_id}: pov.present is false")
        effective_min_pov_decisions = run_min_pov_decisions_override.get(run.run_id)
        if effective_min_pov_decisions is None:
            effective_min_pov_decisions = expected_min_pov_decisions
        if effective_min_pov_decisions is not None and int(run.pov_decisions or 0) < int(effective_min_pov_decisions):
            failures.append(
                f"{run.run_id}: pov.decisions {int(run.pov_decisions or 0)} < minPovDecisions {int(effective_min_pov_decisions)}"
            )
        if run_require_ocr_events_present.get(run.run_id, False) and not bool(run.ocr_events_present):
            failures.append(f"{run.run_id}: ocr events missing (ocr.read)")
        if run_require_ocr_payload_schema_ok.get(run.run_id, False) and not bool(run.ocr_payload_schema_ok):
            failures.append(f"{run.run_id}: ocr payload schema check failed")
        if run_require_seg_events_present.get(run.run_id, False) and not bool(run.seg_events_present):
            failures.append(f"{run.run_id}: seg events missing (seg.segment)")
        if run_require_seg_payload_schema_ok.get(run.run_id, False) and not bool(run.seg_payload_schema_ok):
            failures.append(f"{run.run_id}: seg payload schema check failed")
        if run_require_depth_events_present.get(run.run_id, False) and not bool(run.depth_events_present):
            failures.append(f"{run.run_id}: depth events missing (depth.estimate)")
        if run_require_depth_payload_schema_ok.get(run.run_id, False) and not bool(run.depth_payload_schema_ok):
            failures.append(f"{run.run_id}: depth payload schema check failed")
        if run_require_slam_pose_events_present.get(run.run_id, False) and not bool(run.slam_pose_events_present):
            failures.append(f"{run.run_id}: slam pose events missing (slam.pose)")
        if run_require_slam_pose_payload_schema_ok.get(run.run_id, False) and not bool(run.slam_pose_payload_schema_ok):
            failures.append(f"{run.run_id}: slam pose payload schema check failed")
        if run_require_seg_prompt_events_present.get(run.run_id, False) and not bool(run.seg_prompt_events_present):
            failures.append(f"{run.run_id}: seg prompt events missing (seg.prompt)")
        if run_require_seg_prompt_payload_schema_ok.get(run.run_id, False) and not bool(run.seg_prompt_payload_schema_ok):
            failures.append(f"{run.run_id}: seg prompt payload schema check failed")
        if run_require_seg_prompt_budget_present.get(run.run_id, False) and not bool(run.seg_prompt_budget_present):
            failures.append(f"{run.run_id}: seg prompt payload budget fields missing")
        if run_require_seg_prompt_truncation_present.get(run.run_id, False) and not bool(run.seg_prompt_truncation_present):
            failures.append(f"{run.run_id}: seg prompt payload truncation fields missing")
        if run_require_seg_prompt_packed.get(run.run_id, False) and int(run.seg_prompt_packed_true_count or 0) <= 0:
            failures.append(f"{run.run_id}: seg prompt payload packed=true missing")
        if run_require_seg_context_present.get(run.run_id, False) and not bool(run.seg_context_present):
            failures.append(f"{run.run_id}: seg context missing")
        if run_require_seg_context_schema_ok.get(run.run_id, False) and not bool(run.seg_context_schema_ok):
            failures.append(f"{run.run_id}: seg context schema check failed")
        if run_require_slam_context_present.get(run.run_id, False) and not bool(run.slam_context_present):
            failures.append(f"{run.run_id}: slam context missing")
        if run_require_slam_context_schema_ok.get(run.run_id, False) and not bool(run.slam_context_schema_ok):
            failures.append(f"{run.run_id}: slam context schema check failed")
        if run_require_plan_request_events_present.get(run.run_id, False) and not bool(run.plan_request_events_present):
            failures.append(f"{run.run_id}: plan.request events missing")
        if run_require_plan_request_schema_ok.get(run.run_id, False) and not bool(run.plan_request_schema_ok):
            failures.append(f"{run.run_id}: plan.request payload schema check failed")
        if run_require_plan_context_events_present.get(run.run_id, False) and not bool(run.plan_context_events_present):
            failures.append(f"{run.run_id}: plan.context_alignment events missing")
        if run_require_plan_context_schema_ok.get(run.run_id, False) and not bool(run.plan_context_schema_ok):
            failures.append(f"{run.run_id}: plan.context_alignment payload schema check failed")
        if run_require_plan_context_slam_present.get(run.run_id, False) and not bool(run.plan_context_slam_present):
            failures.append(f"{run.run_id}: plan.context_alignment slam fields missing")
        if run_require_plan_context_slam_schema_ok.get(run.run_id, False) and not bool(run.plan_context_slam_schema_ok):
            failures.append(f"{run.run_id}: plan.context_alignment slam payload schema check failed")
        if run_require_plan_context_pack_events_present.get(run.run_id, False) and not bool(
            run.plan_context_pack_events_present
        ):
            failures.append(f"{run.run_id}: plan.context_pack events missing")
        if run_require_plan_context_pack_schema_ok.get(run.run_id, False) and not bool(run.plan_context_pack_schema_ok):
            failures.append(f"{run.run_id}: plan.context_pack payload schema check failed")
        if run_require_frame_e2e_events_present.get(run.run_id, False) and not bool(run.frame_e2e_events_present):
            failures.append(f"{run.run_id}: frame.e2e events missing")
        if run_require_frame_e2e_schema_ok.get(run.run_id, False) and not bool(run.frame_e2e_schema_ok):
            failures.append(f"{run.run_id}: frame.e2e payload schema check failed")
        if run_require_frame_input_events_present.get(run.run_id, False) and not bool(run.frame_input_events_present):
            failures.append(f"{run.run_id}: frame.input events missing")
        if run_require_frame_input_schema_ok.get(run.run_id, False) and not bool(run.frame_input_schema_ok):
            failures.append(f"{run.run_id}: frame.input payload schema check failed")
        if run_require_frame_ack_events_present.get(run.run_id, False) and not bool(run.frame_ack_events_present):
            failures.append(f"{run.run_id}: frame.ack events missing")
        if run_require_frame_ack_schema_ok.get(run.run_id, False) and not bool(run.frame_ack_schema_ok):
            failures.append(f"{run.run_id}: frame.ack payload schema check failed")
        if run_require_frame_user_e2e_events_present.get(run.run_id, False) and not bool(run.frame_user_e2e_events_present):
            failures.append(f"{run.run_id}: frame.user_e2e events missing")
        if run_require_frame_user_e2e_schema_ok.get(run.run_id, False) and not bool(run.frame_user_e2e_schema_ok):
            failures.append(f"{run.run_id}: frame.user_e2e payload schema check failed")
        if run_require_models_present.get(run.run_id, False) and not bool(run.models_present):
            failures.append(f"{run.run_id}: models.manifest events missing")
        if run_require_models_missing_required_zero.get(run.run_id, False) and int(run.models_missing_required_total or 0) > 0:
            failures.append(
                f"{run.run_id}: models missingRequiredTotal {int(run.models_missing_required_total or 0)} > 0"
            )
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

    if suite_name.strip().lower() == "contract":
        contract_lock_ok, contract_lock_detail = _run_contract_lock_check()
        if not contract_lock_ok:
            failures.append("contract lock check failed (python Gateway/scripts/verify_contracts.py --check-lock)")

    result = {
        "suiteName": suite_name,
        "suitePath": str(suite_path),
        "generatedAtMs": int(datetime.now(timezone.utc).timestamp() * 1000),
        "failOnDrop": bool(fail_on_drop),
        "failOnCriticalFn": bool(fail_on_critical_fn),
        "baselinePath": str(baseline_path) if baseline_path is not None else "",
        "runs": [run.to_dict() for run in run_summaries],
        "failures": failures,
        "meta": {
            "contractsOk": contract_lock_ok,
            "contractsDetail": contract_lock_detail,
        },
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
    meta = result.get("meta", {})
    if isinstance(meta, dict) and meta.get("contractsOk") is not None:
        print(f"[contracts] ok={meta.get('contractsOk')}")
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
            inference = row.get("inference", {}) if isinstance(row.get("inference"), dict) else {}
            inference_ocr = inference.get("ocr", {}) if isinstance(inference.get("ocr"), dict) else {}
            inference_risk = inference.get("risk", {}) if isinstance(inference.get("risk"), dict) else {}
            ocr_backend = inference_ocr.get("backend", "")
            risk_backend = inference_risk.get("backend", "")
            ocr_model = inference_ocr.get("model", "")
            risk_model = inference_risk.get("model", "")
            print(
                "[run] {run_id}: score={score} baseline={baseline} delta={delta} "
                "confirmTimeouts={confirm_timeouts} critical_fn={critical_fn} riskDelayP90={risk_delay_p90} riskDelayMax={risk_delay_max} "
                "riskLatencyP90={risk_latency_p90} riskLatencyMax={risk_latency_max} segF1@0.5={seg_f1} segCoverage={seg_cov} segLatencyP90={seg_p90} "
                "depthAbsRel={depth_absrel} depthDelta1={depth_delta1} depthCoverage={depth_cov} depthLatencyP90={depth_p90} "
                "slamTrackingRate={slam_tracking_rate} slamLostRate={slam_lost_rate} slamRelocalized={slam_relocalized} slamLatencyP90={slam_p90} "
                "ocrEventsPresent={ocr_events_present} ocrPayloadSchemaOk={ocr_payload_schema_ok} "
                "segEventsPresent={seg_events_present} segPayloadSchemaOk={seg_payload_schema_ok} depthEventsPresent={depth_events_present} depthPayloadSchemaOk={depth_payload_schema_ok} "
                "slamPoseEventsPresent={slam_pose_events_present} slamPosePayloadSchemaOk={slam_pose_payload_schema_ok} "
                "segPromptEventsPresent={seg_prompt_events_present} segPromptPayloadSchemaOk={seg_prompt_payload_schema_ok} "
                "segPromptBudgetPresent={seg_prompt_budget_present} segPromptTruncationPresent={seg_prompt_truncation_present} "
                "segPromptPackedTrueCount={seg_prompt_packed_true_count} "
                "segContextPresent={seg_context_present} segContextSchemaOk={seg_context_schema_ok} "
                "segContextChars={seg_context_chars} segContextSegmentsOut={seg_context_segments_out} "
                "slamContextPresent={slam_context_present} slamContextSchemaOk={slam_context_schema_ok} "
                "slamCtxCharsP90={slam_ctx_chars_p90} slamTrackingRateMean={slam_tracking_rate_mean} "
                "planRequestEventsPresent={plan_request_events_present} planRequestSchemaOk={plan_request_schema_ok} "
                "planRequestSegIncludedCount={plan_request_seg_included_count} planRequestSegCharsTotal={plan_request_seg_chars_total} "
                "planContextEventsPresent={plan_context_events_present} planContextSchemaOk={plan_context_schema_ok} "
                "planCtxUsedTrueCount={plan_ctx_used_true_count} planSegCoverageP90={plan_seg_coverage_p90} planPovCoverageP90={plan_pov_coverage_p90} "
                "planContextSlamPresent={plan_context_slam_present} planContextSlamSchemaOk={plan_context_slam_schema_ok} "
                "planSlamCoverageP90={plan_slam_coverage_p90} planSlamUsedTrueCount={plan_slam_used_true_count} "
                "planContextPackPresent={plan_context_pack_present} planContextPackSchemaOk={plan_context_pack_schema_ok} "
                "planCtxTruncRate={plan_ctx_trunc_rate} planCtxCharsP90={plan_ctx_chars_p90} "
                "frameE2eEventsPresent={frame_e2e_events_present} frameE2eSchemaOk={frame_e2e_schema_ok} "
                "frameE2eCount={frame_e2e_count} frameE2eTotalMsP90={frame_e2e_total_ms_p90} "
                "frameInputEventsPresent={frame_input_events_present} frameInputSchemaOk={frame_input_schema_ok} "
                "frameAckEventsPresent={frame_ack_events_present} frameAckSchemaOk={frame_ack_schema_ok} "
                "frameUserE2eEventsPresent={frame_user_e2e_events_present} frameUserE2eSchemaOk={frame_user_e2e_schema_ok} "
                "frameUserE2eNegativeCount={frame_user_e2e_negative_count} frameUserE2eDuplicateCount={frame_user_e2e_duplicate_count} "
                "modelsPresent={models_present} modelsSchemaOk={models_schema_ok} "
                "modelsMissingRequiredTotal={models_missing_required_total} modelsEnabledTotal={models_enabled_total} "
                "povPresent={pov_present} povDecisions={pov_decisions} povTokenApprox={pov_token_approx} source={schema_src} "
                "ocr={ocr_backend}/{ocr_model} risk={risk_backend}/{risk_model}".format(
                    run_id=run_id,
                    score=score,
                    baseline=baseline,
                    delta=delta,
                    confirm_timeouts=confirm_timeouts,
                    critical_fn=row.get("depthRisk", {}).get("missCriticalCount", None),
                    risk_delay_p90=row.get("depthRisk", {}).get("delayP90", None),
                    risk_delay_max=row.get("depthRisk", {}).get("delayMax", None),
                    risk_latency_p90=row.get("riskLatency", {}).get("p90", None),
                    risk_latency_max=row.get("riskLatency", {}).get("max", None),
                    seg_f1=row.get("seg", {}).get("f1At50", None),
                    seg_cov=row.get("seg", {}).get("coverage", None),
                    seg_p90=row.get("seg", {}).get("latencyP90", None),
                    depth_absrel=row.get("depth", {}).get("absRel", None),
                    depth_delta1=row.get("depth", {}).get("delta1", None),
                    depth_cov=row.get("depth", {}).get("coverage", None),
                    depth_p90=row.get("depth", {}).get("latencyP90", None),
                    slam_tracking_rate=row.get("slam", {}).get("trackingRate", None),
                    slam_lost_rate=row.get("slam", {}).get("lostRate", None),
                    slam_relocalized=row.get("slam", {}).get("relocalizedCount", None),
                    slam_p90=row.get("slam", {}).get("latencyP90", None),
                    ocr_events_present=row.get("segLint", {}).get("ocrEventsPresent", False),
                    ocr_payload_schema_ok=row.get("segLint", {}).get("ocrPayloadSchemaOk", False),
                    seg_events_present=row.get("segLint", {}).get("eventsPresent", False),
                    seg_payload_schema_ok=row.get("segLint", {}).get("payloadSchemaOk", False),
                    depth_events_present=row.get("segLint", {}).get("depthEventsPresent", False),
                    depth_payload_schema_ok=row.get("segLint", {}).get("depthPayloadSchemaOk", False),
                    slam_pose_events_present=row.get("segLint", {}).get("slamPoseEventsPresent", False),
                    slam_pose_payload_schema_ok=row.get("segLint", {}).get("slamPosePayloadSchemaOk", False),
                    seg_prompt_events_present=row.get("segLint", {}).get("promptEventsPresent", False),
                    seg_prompt_payload_schema_ok=row.get("segLint", {}).get("promptPayloadSchemaOk", False),
                    seg_prompt_budget_present=row.get("segLint", {}).get("segPromptBudgetPresent", False),
                    seg_prompt_truncation_present=row.get("segLint", {}).get("segPromptTruncationPresent", False),
                    seg_prompt_packed_true_count=row.get("segLint", {}).get("segPromptPackedTrueCount", 0),
                    seg_context_present=row.get("segLint", {}).get("segContextPresent", False),
                    seg_context_schema_ok=row.get("segLint", {}).get("segContextSchemaOk", False),
                    seg_context_chars=row.get("segLint", {}).get("segContextChars", 0),
                    seg_context_segments_out=row.get("segLint", {}).get("segContextSegmentsOut", 0),
                    slam_context_present=row.get("segLint", {}).get("slamContextPresent", False),
                    slam_context_schema_ok=row.get("segLint", {}).get("slamContextSchemaOk", False),
                    slam_ctx_chars_p90=row.get("segLint", {}).get("slamCtxCharsP90", 0),
                    slam_tracking_rate_mean=row.get("segLint", {}).get("slamTrackingRateMean", 0.0),
                    plan_request_events_present=row.get("segLint", {}).get("planRequestEventsPresent", False),
                    plan_request_schema_ok=row.get("segLint", {}).get("planRequestSchemaOk", False),
                    plan_request_seg_included_count=row.get("segLint", {}).get("planRequestSegIncludedCount", 0),
                    plan_request_seg_chars_total=row.get("segLint", {}).get("planRequestSegCharsTotal", 0),
                    plan_context_events_present=row.get("segLint", {}).get("planContextEventsPresent", False),
                    plan_context_schema_ok=row.get("segLint", {}).get("planContextSchemaOk", False),
                    plan_ctx_used_true_count=row.get("segLint", {}).get("planCtxUsedTrueCount", 0),
                    plan_seg_coverage_p90=row.get("segLint", {}).get("planSegCoverageP90", 0.0),
                    plan_pov_coverage_p90=row.get("segLint", {}).get("planPovCoverageP90", 0.0),
                    plan_context_slam_present=row.get("segLint", {}).get("planContextSlamPresent", False),
                    plan_context_slam_schema_ok=row.get("segLint", {}).get("planContextSlamSchemaOk", False),
                    plan_slam_coverage_p90=row.get("segLint", {}).get("planSlamCoverageP90", 0.0),
                    plan_slam_used_true_count=row.get("segLint", {}).get("planSlamUsedTrueCount", 0),
                    plan_context_pack_present=row.get("segLint", {}).get("planContextPackEventsPresent", False),
                    plan_context_pack_schema_ok=row.get("segLint", {}).get("planContextPackSchemaOk", False),
                    plan_ctx_trunc_rate=row.get("segLint", {}).get("planCtxTruncRate", 0.0),
                    plan_ctx_chars_p90=row.get("segLint", {}).get("planCtxCharsP90", 0.0),
                    frame_e2e_events_present=row.get("segLint", {}).get("frameE2eEventsPresent", False),
                    frame_e2e_schema_ok=row.get("segLint", {}).get("frameE2eSchemaOk", False),
                    frame_e2e_count=row.get("segLint", {}).get("frameE2eCount", 0),
                    frame_e2e_total_ms_p90=row.get("segLint", {}).get("frameE2eTotalMsP90", 0.0),
                    frame_input_events_present=row.get("segLint", {}).get("frameInputEventsPresent", False),
                    frame_input_schema_ok=row.get("segLint", {}).get("frameInputSchemaOk", False),
                    frame_ack_events_present=row.get("segLint", {}).get("frameAckEventsPresent", False),
                    frame_ack_schema_ok=row.get("segLint", {}).get("frameAckSchemaOk", False),
                    frame_user_e2e_events_present=row.get("segLint", {}).get("frameUserE2eEventsPresent", False),
                    frame_user_e2e_schema_ok=row.get("segLint", {}).get("frameUserE2eSchemaOk", False),
                    frame_user_e2e_negative_count=row.get("segLint", {}).get("frameUserE2eNegativeCount", 0),
                    frame_user_e2e_duplicate_count=row.get("segLint", {}).get("frameUserE2eDuplicateCount", 0),
                    models_present=row.get("segLint", {}).get("modelsPresent", False),
                    models_schema_ok=row.get("segLint", {}).get("modelsSchemaOk", False),
                    models_missing_required_total=row.get("segLint", {}).get("modelsMissingRequiredTotal", 0),
                    models_enabled_total=row.get("segLint", {}).get("modelsEnabledTotal", 0),
                    pov_present=row.get("pov", {}).get("present", False),
                    pov_decisions=row.get("pov", {}).get("decisions", 0),
                    pov_token_approx=row.get("pov", {}).get("tokenApprox", 0),
                    schema_src=schema_src,
                    ocr_backend=ocr_backend,
                    ocr_model=ocr_model,
                    risk_backend=risk_backend,
                    risk_model=risk_model,
                )
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
    parser.add_argument("--fail-on-critical-fn", action=argparse.BooleanOptionalAction, default=True)
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
            fail_on_critical_fn=bool(args.fail_on_critical_fn),
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
