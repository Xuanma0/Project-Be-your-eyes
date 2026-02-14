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

## Segmentation (mock/http)

Enable segmentation event emission in Gateway:

```powershell
cd Gateway
$env:BYES_ENABLE_SEG="1"
$env:BYES_SEG_BACKEND="mock"   # or http
$env:BYES_SEG_MODEL_ID="mock-seg-v1"
# when using http backend:
# $env:BYES_SEG_HTTP_URL="http://127.0.0.1:19120/seg"
```

Expected evidence:
- `events/events_v1.jsonl` contains `name="seg.segment"` with payload `segmentsCount`, `backend`, `model`, `endpoint`.
- `report.json` contains `inference.seg` inferred from `events_v1`.

Segmentation quality evaluation (bbox IoU/F1/coverage/latency):

```powershell
python scripts/report_run.py --run-package tests/fixtures/run_package_with_seg_gt_min
python scripts/run_regression_suite.py --suite regression/suites/seg_suite.json --baseline regression/baselines/baseline.json --fail-on-drop
```

`report.json -> quality.seg` fields:
- `framesTotal / framesWithGt / framesWithPred / coverage`
- `precision / recall / f1At50 / meanIoU`
- `latencyMs` (`p50/p90/max`)
- `topMisses / topFP` (debug samples)

Leaderboard fields:
- columns: `seg_f1_50`, `seg_coverage`, `seg_latency_p90`
- filters: `min_seg_f1_50`, `min_seg_coverage`, `max_seg_latency_p90`
- sort: `sort=seg_f1_50|seg_coverage|seg_latency_p90`

Future SAM3 path:
- keep `BYES_SEG_BACKEND=http`;
- point `BYES_SEG_HTTP_URL` to external SAM3-compatible service exposing `POST /seg`;
- return `segments` as `{label, score, bbox}`.

Reference seg HTTP chain (Gateway -> inference_service -> reference_seg_service):

```powershell
# terminal 1: reference seg service
python -m uvicorn services.reference_seg_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19231

# terminal 2: inference_service (seg provider=http -> reference seg service)
$env:BYES_SERVICE_SEG_PROVIDER="http"
$env:BYES_SERVICE_SEG_ENDPOINT="http://127.0.0.1:19231/seg"
python -m uvicorn services.inference_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19120

# terminal 3: Gateway replay with seg enabled
cd Gateway
$env:BYES_ENABLE_SEG="1"
$env:BYES_SEG_BACKEND="http"
$env:BYES_SEG_HTTP_URL="http://127.0.0.1:19120/seg"
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_seg_gt_min --reset
python scripts/report_run.py --run-package tests/fixtures/run_package_with_seg_gt_min
```

## Planning API (/api/plan)

Generate an `ActionPlan v1` from POV context + risk events.

Planner backends:
- `mock` (default): built-in deterministic planner in Gateway.
- `http`: calls external planner service (reference service in `services/planner_service`).

Default (`mock`) example:

```powershell
curl -X POST "http://127.0.0.1:8000/api/plan" `
  -H "Content-Type: application/json" `
  -d '{"runPackage":"Gateway/tests/fixtures/run_package_with_risk_gt_and_pov_min","frameSeq":2,"budget":{"maxChars":2000,"maxTokensApprox":256,"mode":"decisions_plus_highlights"},"constraints":{"allowConfirm":true,"allowHaptic":false,"maxActions":3}}'
```

SafetyKernel guardrails:
- `critical`: injects `stop` when missing and forces non-stop actions to `requiresConfirm=true`.
- `high`: forces `requiresConfirm=true` for actions that were not gated.
- trims actions to `constraints.maxActions` and fills default `ttlMs=2000` when absent.

Audit outputs:
- `events/events_v1.jsonl`: appends `plan.generate` and `safety.kernel` events (and `plan.execute` when using `/api/plan/execute`).
- `report.json`: check `plan` for `riskLevel`, action counts/types, and `guardrailsApplied`.
- leaderboard (`/api/run_packages`, `/runs`): `plan_present`, `plan_risk_level`, `plan_actions`, `plan_guardrails`.

Minimal execute + confirm loop:

```powershell
# 1) generate plan
$plan = curl -X POST "http://127.0.0.1:8000/api/plan" `
  -H "Content-Type: application/json" `
  -d '{"runPackage":"Gateway/tests/fixtures/run_package_with_risk_gt_and_pov_min","frameSeq":2,"budget":{"maxChars":2000,"maxTokensApprox":256,"mode":"decisions_plus_highlights"},"constraints":{"allowConfirm":true,"allowHaptic":false,"maxActions":3}}'

# 2) execute plan -> returns uiCommands / pendingConfirms
curl -X POST "http://127.0.0.1:8000/api/plan/execute" `
  -H "Content-Type: application/json" `
  -d "{\"runPackage\":\"Gateway/tests/fixtures/run_package_with_risk_gt_and_pov_min\",\"frameSeq\":2,\"plan\":$plan}"

# 3) submit confirm response
curl -X POST "http://127.0.0.1:8000/api/confirm/response" `
  -H "Content-Type: application/json" `
  -d '{"runId":"fixture-risk-gt","frameSeq":2,"confirmId":"confirm-a1","accepted":true,"runPackage":"Gateway/tests/fixtures/run_package_with_risk_gt_and_pov_min"}'
```

Loop events written to `events/events_v1.jsonl`:
- `plan.execute`
- `ui.command`
- `ui.confirm_request`
- `ui.confirm_response`

HTTP planner (reference service) quick demo:

```powershell
# 1) start planner service
python Gateway/services/planner_service/app.py

# 2) configure Gateway planner backend
set BYES_PLANNER_BACKEND=http
set BYES_PLANNER_ENDPOINT=http://127.0.0.1:19211/plan

# 3) run report/replay and inspect planner metadata + plan quality
python Gateway/scripts/report_run.py --run-package Gateway/tests/fixtures/run_package_with_plan_http_min
```

Validation points:
- `events/events_v1.jsonl` has `plan.generate` payload with planner `backend/model/endpoint`.
- `report.json` includes `plan` and `planQuality`.

POV planner adapter (`provider=pov`) for contract/replay:

```powershell
set BYES_PLANNER_BACKEND=http
set BYES_PLANNER_ENDPOINT=http://127.0.0.1:19211/plan
set BYES_PLANNER_PROVIDER=pov
set BYES_PLANNER_ALLOW_RUN_PACKAGE_PATH=1
python Gateway/scripts/report_run.py --run-package Gateway/tests/fixtures/pov_plan_min
```

Validation points:
- `report.json.plan.planner.backend == "pov"`
- `report.json.povPlan` includes `decisionCoverage`, `actionCoverage`, `consistencyWarnings`
- contract suite includes `fixture_pov_plan_min` to lock this adapter path.

Live POV ingest demo (no `runPackagePath` dependency):

```powershell
# 1) planner service
set BYES_PLANNER_PROVIDER=pov
python Gateway/services/planner_service/app.py

# 2) gateway
python Gateway/main.py

# 3) ingest POV IR and generate plan
curl -X POST "http://127.0.0.1:8000/api/pov/ingest" -H "Content-Type: application/json" -d @Gateway/tests/fixtures/pov_ir_v1_min/pov/pov_ir_v1.json
curl -X POST "http://127.0.0.1:8000/api/plan?provider=pov" -H "Content-Type: application/json" -d "{\"runId\":\"fixture-pov-ir-min\",\"frameSeq\":1,\"budget\":{\"maxChars\":2000,\"maxTokensApprox\":256,\"mode\":\"decisions_plus_highlights\"},\"constraints\":{\"allowConfirm\":true,\"allowHaptic\":false,\"maxActions\":3}}"
```

### Planner LLM Adapter (Optional)

No key is required by default. LLM mode is opt-in and falls back to reference planner when timeout/HTTP/JSON/schema checks fail.

```powershell
set BYES_PLANNER_BACKEND=http
set BYES_PLANNER_ENDPOINT=http://127.0.0.1:19211/plan
set BYES_PLANNER_PROVIDER=llm
set BYES_PLANNER_LLM_ENDPOINT=http://127.0.0.1:8088/generate
set BYES_PLANNER_LLM_TIMEOUT_MS=2500
set BYES_PLANNER_PROMPT_VERSION=v1
```

Traceability fields:
- `events/events_v1.jsonl` (`plan.generate`): `plannerProvider`, `promptVersion`, `fallbackUsed`, `fallbackReason`, `jsonValid`
- `report.json` (`plan.planner.*`, `planQuality.*`): fallback and JSON validity state
- `/api/run_packages`: `plan_fallback_used`, `plan_json_valid`, `plan_prompt_version`

## Planner Evaluation And Ablation

`report.json` now includes `planEval` with:
- interaction cost: `confirm.requests/responses/timeouts/pending`
- safety actions: `actions.stopCount`, `actions.blockingCount`
- guardrail dependency: `guardrails.appliedCount`, `guardrails.overrideRate`
- over-cautious behavior: `overcautious.rate` (`riskLevel!=critical` yet `stop/confirm`)
- latency: `latencyMs` (plan.generate) and `executeLatencyMs` (plan.execute)

One-command sweep (provider/prompt/budget):

```powershell
python Gateway/scripts/ablate_planner.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_and_pov_min --providers reference,llm --prompt-versions v1 --pov-budgets 128,256
```

Output:
- `%TEMP%\\byes_plan_ablation\\latest.json`
- `%TEMP%\\byes_plan_ablation\\latest.md`

Recommendation rule:
- minimize `confirm_timeouts` subject to `critical_fn==0`
- then minimize `plan_latency_p90`
- then maximize `qualityScore`

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
- `plan_present`, `plan_risk_level`, `plan_actions`, `plan_guardrails`, `plan_score`
- `plan_fallback_used`, `plan_json_valid`, `plan_prompt_version`

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
