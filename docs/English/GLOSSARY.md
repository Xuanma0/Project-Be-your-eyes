# Glossary

## RunPackage

A replayable package containing frames, metadata, events, and metrics inputs/outputs. It enables deterministic offline evaluation.

## events_v1

Normalized event stream file at `events/events_v1.jsonl`. Tool results (OCR/risk) use a stable schema and include authoritative `event.latencyMs`.

## qualityScore

Composite quality metric in `report.json` (`quality.qualityScore`) with breakdown across OCR/risk/safety behavior components.

## Critical FN (critical false negative)

A missed critical hazard compared to ground truth. In reports: `quality.depthRisk.critical.missCriticalCount`.

## Leaderboard

Run list APIs/pages (`/api/run_packages`, `/runs`) that summarize quality, latency, confirm behavior, and critical misses.

## Regression Gate

Automated pass/fail checks in `run_regression_suite.py` and CI:
- quality drop gate,
- critical FN hard gate (`missCriticalCount` must stay `0` for gated runs).

## Inference Backend

Gateway-side OCR/risk backend mode (`mock` or `http`) used to fetch model inference results.

## inference_service Provider

Service-side implementation selected by env:
- OCR provider (`reference`, `tesseract`, `paddleocr`)
- risk provider (`reference`, `heuristic`)
- depth provider (`none`, `synth`, `midas`, `onnx`)

## Latch / Preempt / Fallback

Safety-behavior signals summarized in report:
- latch: holding safe-state behavior,
- preempt: early intervention before full plan completion,
- fallback: degraded local fallback actions.

## Sweep

Input-size parameter scan (`sweep_depth_input_size.py`) to quantify speed/quality trade-off for ONNX depth.

## Calibration

Threshold grid search (`calibrate_risk_thresholds.py`) used to minimize FP and enforce `critical FN == 0`, with explain reports for misses.

## Depth Temporal Metrics

Report-level consistency metrics computed from consecutive depth grids:
- `jitterAbs`: frame-to-frame absolute depth change in ROI.
- `flickerRateNear`: near-obstacle mask XOR ratio between frames.
- `scaleDriftProxy`: frame-to-frame median depth drift in ROI.

## Ref View Strategy

DA3-side reference-view selection hint (for example `auto_ref`, `first`, `middle`) forwarded via `depth.estimate.payload.meta.refViewStrategy`.

## Plan Request v1

Structured planner request contract (`byes.plan_request.v1`) that carries risk/seg/pov/slam/costmap context fragments and metadata.

## Context Pack

Budgeted text+stats package generated from structured context signals:
- `seg.context.v1`
- `slam.context.v1`
- `plan.context_pack.v1`
- `costmap.context.v1`

## Costmap / Costmap Fused

- `byes.costmap.v1`: per-frame local occupancy-cost grid from depth/seg/slam.
- `byes.costmap_fused.v1`: temporal fused grid (EMA/optional pose shift) with stability statistics.

## Matrix Profile

A named benchmark runtime configuration in `run_dataset_benchmark.py` (services/env/prehooks), used for cross-profile comparison.

## Prehook

Per-run-package preprocessing step in benchmark matrix (for example `pyslam_ingest` / `pyslam_run`) executed before report aggregation.
