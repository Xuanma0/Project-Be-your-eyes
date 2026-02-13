# Architecture Overview

## One-Line Summary

Unity (or replay fixtures) sends frames to Gateway; Gateway calls pluggable inference backends, emits normalized `events_v1`, then report/leaderboard/regression consume those artifacts for reproducible safety evaluation.

## End-to-End Data Flow

```text
Unity / RunPackage replay
        |
        v
Gateway (/api/frame, scheduler, fusion, safety)
        |
        +--> inference backend: mock or http
                 |
                 v
        inference_service (/ocr, /risk)
                 |
                 v
events/events_v1.jsonl  + metrics_before/after
        |
        v
report_run.py -> report.json + report.md
        |
        +--> /api/run_packages + /runs leaderboard
        |
        +--> run_regression_suite.py + CI gate
```

## Core Components

- `Gateway/main.py`
  - Runtime APIs, run package ingestion, leaderboard APIs/pages.
- `Gateway/byes/*`
  - Scheduling, safety kernel, metrics, inference backend adapters.
- `Gateway/services/inference_service/*`
  - OCR/risk provider selection and optional ONNX depth inference.
- `Gateway/scripts/*`
  - replay/report/regression/sweep/calibration tooling.

## Event Contract

Primary artifact:
- `events/events_v1.jsonl`

Typical risk result event contains:
- `category=tool`, `name=risk.hazards`, `phase=result`, `status=ok`
- `event.latencyMs` (authoritative latency)
- `payload.backend`, `payload.model`, `payload.endpoint`
- optional `payload.debug` (depth/timing/threshold evidence)

## Quality And Safety Loop

1. Replay fixture/run package.
2. Generate report (`report.json`).
3. Inspect:
   - `quality.depthRisk.critical.missCriticalCount`
   - `quality.riskLatencyMs`
   - `quality.qualityScoreBreakdown`
4. Compare with baseline in regression suite.
5. CI gate fails if:
   - quality drop exceeds threshold
   - critical FN gate violated (`missCriticalCount > 0`).

## Why This Matters For Review

- Reproducibility: same fixture -> same report/gate outcome.
- Explainability: event-level evidence + report-level summaries.
- Safety-first evolution: calibration and hard gating prevent silent regressions.
