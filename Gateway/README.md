# Gateway Developer & Evaluation Guide

TL;DR:
- `Gateway` is the runtime hub: receives frames/events, calls inference backends, emits normalized events.
- It supports replay-first evaluation: `RunPackage -> events_v1 -> report.json -> leaderboard -> regression gate`.
- For provider deployment details, read `Gateway/services/inference_service/README.md`.

## Common Commands (PowerShell)

```powershell
cd Gateway
python -m pytest -q
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_risk_gt_min --reset
python scripts/report_run.py --run-package tests/fixtures/run_package_with_risk_gt_min
python scripts/run_regression_suite.py --suite regression/suites/baseline_suite.json --baseline regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
```

## What Gateway Does

- Accepts Unity/client inputs and orchestrates tools/backends.
- Records/normalizes events (`events/events_v1.jsonl`) for deterministic analysis.
- Generates quality reports (`report.json` + markdown) from replay/live artifacts.
- Exposes run leaderboard APIs and dashboard pages (`/api/run_packages`, `/runs`).
- Enforces regression thresholds in CI (including `critical FN == 0` gate).

## Evaluation Workflow

### 1) Replay run package

```powershell
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_risk_gt_min --reset
```

### 2) Generate report

```powershell
python scripts/report_run.py --run-package tests/fixtures/run_package_with_risk_gt_min
```

### 3) Inspect key files

- `events/events_v1.jsonl`: authoritative per-event latency (`event.latencyMs`) and tool metadata.
- `report.json`: inference summary, OCR/risk quality, safety behavior, score breakdown.

### 4) Compare against baseline suite

```powershell
python scripts/run_regression_suite.py --suite regression/suites/baseline_suite.json --baseline regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
```

Gate highlights:
- score drop gate (`--fail-on-drop`)
- critical safety gate (`--fail-on-critical-fn`, default enabled)
- run fails if `report.quality.depthRisk.critical.missCriticalCount > 0`

## POV Contract (POV-compiler -> BYES)

- Contract schema source of truth: `../schemas/pov_ir_v1.schema.json`
- Ingest one POV IR into a run package:

```powershell
python scripts/ingest_pov_ir.py --run-package <run_package_dir> --pov-ir <pov_ir.json> --strict 1
```

- Contract regression suite:

```powershell
python scripts/run_regression_suite.py --suite regression/suites/contract_suite.json --baseline regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
```

## POV Context API

Build a budget-controlled context pack from POV IR:

```powershell
curl -X POST "http://127.0.0.1:8000/api/pov/context" `
  -H "Content-Type: application/json" `
  -d '{"runPackage":"Gateway/tests/fixtures/pov_ir_v1_min","budget":{"maxChars":2000,"maxTokensApprox":500},"mode":"decisions_plus_highlights"}'
```

Request knobs:
- `mode`: `decisions_only` | `decisions_plus_highlights` | `full`
- `budget.maxChars`: prompt character cap
- `budget.maxTokensApprox`: approximate token cap (`ceil(chars/4)`)

Audit outputs:
- `events/events_v1.jsonl`: appends `pov.context` event with output/truncation stats.
- `report.json`: check `povContext` for default-budget output stats and truncation.

## Ablation: POV Budget Sweep

Run one command to compare context budgets:

```powershell
python scripts/run_ablation_pov_budget.py --run-package tests/fixtures/run_package_with_risk_gt_and_pov_min --budgets 256,512,1024 --mode decisions_plus_highlights --use-http 0
```

Outputs:
- `%TEMP%\byes_pov_ablation\latest.json`
- `%TEMP%\byes_pov_ablation\latest.md`

How to read recommendation:
- default rule is `minimize riskLatencyP90` with `critical_fn==0`, then maximize `qualityScore`.
- use `latest.md` table to inspect context compression (`ctxTok`, `ctxChars`) against quality/latency metrics.

## Leaderboard And Reports

- API list: `GET /api/run_packages`
- HTML list: `GET /runs`
- Run details: `GET /runs/{run_id}`
- Compare two runs: `GET /runs/compare?ids=<runA>,<runB>`
- Export:
  - `GET /api/run_packages/export.json`
  - `GET /api/run_packages/export.csv`

Important leaderboard fields:
- `quality_score`
- `confirm_timeouts`
- `missCriticalCount` / `critical_misses`
- `risk_latency_p90`, `risk_latency_max`

## Script Index (Most Used)

- `scripts/replay_run_package.py`: replay a run package to produce events/metrics.
- `scripts/report_run.py`: generate report from one run package.
- `scripts/report_packages.py`: batch report generation.
- `scripts/lint_run_package.py`: validate package structure and event schema.
- `scripts/run_regression_suite.py`: baseline comparison and gate checks.
- `scripts/bench_risk_latency.py`: summarize risk latency from events.
- `scripts/sweep_depth_input_size.py`: compare ONNX depth input sizes.
- `scripts/calibrate_risk_thresholds.py`: threshold grid search with FN report.

## References

- Root project entry: `README.md`
- Inference providers and deployment: `Gateway/services/inference_service/README.md`
- Event schema details: `docs/event_schema_v1.md`
- Architecture overview: `docs/ARCHITECTURE.md`
- 5-minute demo script: `docs/QUICK_DEMO.md`
- Terminology: `docs/GLOSSARY.md`
- Command index: `docs/COMMANDS.md`
