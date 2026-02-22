# Gateway Developer & Evaluation Guide

[中文说明 / Chinese Version](docs/Chinese/README.md)

TL;DR:
- `Gateway` is the runtime hub: receives frames/events, calls inference backends, emits normalized events.
- It supports replay-first evaluation: `RunPackage -> events_v1 -> report.json -> leaderboard -> regression gate`.
- For provider deployment details, read `Gateway/services/inference_service/README.md`.

## Environment Setup (PowerShell, required)

Option A: `venv`

```powershell
cd Gateway
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

Option B: conda

```powershell
cd Gateway
conda create -n byes python=3.11 -y
conda activate byes
python -m pip install -U pip
python -m pip install -r requirements.txt
```

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
# optional open-vocabulary targets:
# $env:BYES_SEG_TARGETS="person,car,stairs"
# $env:BYES_SEG_TARGETS_JSON='["person","car","stairs"]'
# optional seg prompt (JSON has higher priority than TEXT):
# $env:BYES_SEG_PROMPT_TEXT="find stairs and handrail"
# $env:BYES_SEG_PROMPT_JSON='{\"schemaVersion\":\"byes.seg_request.v1\",\"targets\":[\"stairs\"],\"text\":\"find stairs and handrail\",\"meta\":{\"promptVersion\":\"v1\"}}'
# optional seg prompt budget (v4.51):
# $env:BYES_SEG_PROMPT_MAX_CHARS="256"
# $env:BYES_SEG_PROMPT_MAX_TARGETS="8"
# $env:BYES_SEG_PROMPT_MAX_BOXES="4"
# $env:BYES_SEG_PROMPT_MAX_POINTS="8"
# $env:BYES_SEG_PROMPT_BUDGET_MODE="targets_text_boxes_points"
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
- optional `targets` prompt passthrough is already wired end-to-end (`BYES_SEG_TARGETS` / `BYES_SEG_TARGETS_JSON`).
- optional rich prompt passthrough is supported via `BYES_SEG_PROMPT_TEXT` / `BYES_SEG_PROMPT_JSON` and recorded as `seg.prompt` events.
- prompt budget packer is built-in; `seg.prompt`/`report.segPrompt` include `budget`, `out`, `truncation`, `complexity`, `truncationRate`.

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
$env:BYES_SEG_TARGETS="person,chair"  # matches run_package_with_seg_gt_min fixture labels
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_seg_gt_min --reset
python scripts/report_run.py --run-package tests/fixtures/run_package_with_seg_gt_min
```

SAM3 seg HTTP chain (Gateway -> inference_service -> sam3_seg_service):

```powershell
# terminal 1: sam3 seg service (fixture mode for deterministic runs)
$env:BYES_SAM3_MODE="fixture"
$env:BYES_SAM3_FIXTURE_DIR="Gateway/tests/fixtures/run_package_with_sam3_fixture_seg_min"
$env:BYES_SAM3_MODEL_ID="sam3-v1"
python -m uvicorn services.sam3_seg_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19271

# terminal 2: inference_service (seg provider=http -> sam3 seg service)
$env:BYES_SERVICE_SEG_PROVIDER="http"
$env:BYES_SERVICE_SEG_ENDPOINT="http://127.0.0.1:19271/seg"
$env:BYES_SERVICE_SEG_HTTP_DOWNSTREAM="sam3"
$env:BYES_SERVICE_SEG_MODEL_ID="sam3-v1"
python -m uvicorn services.inference_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19120

# terminal 3: Gateway replay/report with seg enabled
cd Gateway
$env:BYES_ENABLE_SEG="1"
$env:BYES_SEG_BACKEND="http"
$env:BYES_SEG_HTTP_URL="http://127.0.0.1:19120/seg"
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_sam3_fixture_seg_min --reset
python scripts/report_run.py --run-package tests/fixtures/run_package_with_sam3_fixture_seg_min
```

SAM3 model readiness check:
- `/api/models` will require `BYES_SAM3_CKPT_PATH` when `BYES_ENABLE_SEG=1`, `BYES_SEG_BACKEND=http`, and downstream is `sam3`.
- Use `python scripts/verify_models.py --check --quiet` to fail fast on missing checkpoint/endpoint config.

Prompt + mask HTTP e2e (deterministic fixture):

```powershell
# terminal 1: reference seg service (prompt+mask fixture source)
$env:BYES_REF_SEG_FIXTURE_DIR="Gateway/tests/fixtures/run_package_with_seg_prompt_and_mask_gt_min"
python -m uvicorn services.reference_seg_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19231

# terminal 2: inference_service (seg provider=http)
$env:BYES_SERVICE_SEG_PROVIDER="http"
$env:BYES_SERVICE_SEG_ENDPOINT="http://127.0.0.1:19231/seg"
python -m uvicorn services.inference_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19120

# terminal 3: Gateway + replay/report
cd Gateway
$env:BYES_ENABLE_SEG="1"
$env:BYES_SEG_BACKEND="http"
$env:BYES_SEG_HTTP_URL="http://127.0.0.1:19120/seg"
$env:BYES_SEG_PROMPT_JSON='{\"schemaVersion\":\"byes.seg_request.v1\",\"targets\":[\"person\"],\"text\":\"find person\",\"meta\":{\"promptVersion\":\"v1\"}}'
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_seg_prompt_and_mask_gt_min --reset
python scripts/report_run.py --run-package tests/fixtures/run_package_with_seg_prompt_and_mask_gt_min
```

Expected evidence:
- `events/events_v1.jsonl` includes both `seg.prompt` and `seg.segment`.
- `seg.segment.payload.segments[*].mask` keeps `rle_v1`.
- `report.json -> quality.seg` includes `maskCoverage`, `maskFramesWithGt`, `maskFramesWithPred`.

## Depth Estimation (mock/http)

Enable depth event emission in Gateway:

```powershell
cd Gateway
$env:BYES_ENABLE_DEPTH="1"
$env:BYES_DEPTH_BACKEND="mock"   # or http
$env:BYES_DEPTH_MODEL_ID="mock-depth-v1"
# when using http backend:
# $env:BYES_DEPTH_HTTP_URL="http://127.0.0.1:19120/depth"
```

Expected evidence:
- `events/events_v1.jsonl` contains `name="depth.estimate"` with `grid`, `backend`, `model`, `endpoint`.
- `report.json -> inference.depth` is inferred from `depth.estimate`.
- `report.json -> quality.depth` includes `absRel`, `rmse`, `delta1`, `coverage`, `latencyMs`.

Depth quality evaluation (grid metrics):

```powershell
python scripts/report_run.py --run-package tests/fixtures/run_package_with_depth_gt_min
python scripts/run_regression_suite.py --suite regression/suites/contract_suite.json --baseline regression/baselines/baseline.json --fail-on-drop
```

`report.json -> quality.depth` fields:
- `framesTotal / framesWithGt / framesWithPred / coverage`
- `absRel / rmse / delta1`
- `latencyMs` (`p50/p90/max`)
- `topBadCells` (debug samples)

Leaderboard fields:
- columns: `depth_absrel`, `depth_rmse`, `depth_delta1`, `depth_coverage`, `depth_latency_p90`
- filters: `min_depth_delta1`, `max_depth_absrel`, `min_depth_coverage`, `max_depth_latency_p90`
- sort: `sort=depth_absrel|depth_rmse|depth_delta1|depth_coverage|depth_latency_p90`

Reference depth HTTP chain (Gateway -> inference_service -> reference_depth_service):

```powershell
# terminal 1: reference depth service
python -m uvicorn services.reference_depth_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19241

# terminal 2: inference_service (depth provider=http -> reference depth service)
$env:BYES_SERVICE_DEPTH_PROVIDER="http"
$env:BYES_SERVICE_DEPTH_ENDPOINT="http://127.0.0.1:19241/depth"
$env:BYES_SERVICE_DEPTH_MODEL_ID="reference-depth-v1"
python -m uvicorn services.inference_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19120

# terminal 3: Gateway replay/report with depth enabled
cd Gateway
$env:BYES_ENABLE_DEPTH="1"
$env:BYES_DEPTH_BACKEND="http"
$env:BYES_DEPTH_HTTP_URL="http://127.0.0.1:19120/depth"
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_depth_gt_min --reset
python scripts/report_run.py --run-package tests/fixtures/run_package_with_depth_gt_min
```

DA3 depth HTTP chain (Gateway -> inference_service -> da3_depth_service):

```powershell
# terminal 1: da3 depth service (fixture mode for deterministic runs)
$env:BYES_DA3_MODE="fixture"
$env:BYES_DA3_FIXTURE_DIR="Gateway/tests/fixtures/run_package_with_da3_fixture_depth_min"
$env:BYES_DA3_MODEL_ID="da3-v1"
python -m uvicorn services.da3_depth_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19281

# terminal 2: inference_service (depth provider=http -> da3 depth service)
$env:BYES_SERVICE_DEPTH_PROVIDER="http"
$env:BYES_SERVICE_DEPTH_ENDPOINT="http://127.0.0.1:19281/depth"
$env:BYES_SERVICE_DEPTH_HTTP_DOWNSTREAM="da3"
$env:BYES_SERVICE_DEPTH_MODEL_ID="da3-v1"
python -m uvicorn services.inference_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19120

# terminal 3: Gateway replay/report with depth enabled
cd Gateway
$env:BYES_ENABLE_DEPTH="1"
$env:BYES_DEPTH_BACKEND="http"
$env:BYES_DEPTH_HTTP_URL="http://127.0.0.1:19120/depth"
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_da3_fixture_depth_min --reset
python scripts/report_run.py --run-package tests/fixtures/run_package_with_da3_fixture_depth_min
```

DA3 model readiness check:
- `/api/models` will require `BYES_DA3_MODEL_PATH` when `BYES_ENABLE_DEPTH=1`, `BYES_DEPTH_BACKEND=http`, and depth downstream is `da3`.
- Use `python scripts/verify_models.py --check --quiet` to fail fast on missing model/endpoint config.

## OCR (mock/http)

Enable OCR event emission in Gateway:

```powershell
cd Gateway
$env:BYES_ENABLE_OCR="1"
$env:BYES_OCR_BACKEND="mock"   # or http
$env:BYES_OCR_MODEL_ID="mock-ocr-v1"
# when using http backend:
# $env:BYES_OCR_HTTP_URL="http://127.0.0.1:19120/ocr"
```

Expected evidence:
- `events/events_v1.jsonl` contains `name="ocr.read"` with payload `lines`, `linesCount`, `backend`, `model`, `endpoint`.
- `report.json -> inference.ocr` is inferred from `ocr.read`.
- `report.json -> quality.ocr` includes `exactMatchRate`, `cer`, `coverage`, `latencyMs`.

OCR quality evaluation:

```powershell
python scripts/report_run.py --run-package tests/fixtures/run_package_with_ocr_gt_min
python scripts/run_regression_suite.py --suite regression/suites/contract_suite.json --baseline regression/baselines/baseline.json --fail-on-drop
```

`report.json -> quality.ocr` fields:
- `framesTotal / framesWithGt / framesWithPred / coverage`
- `exactMatchRate / cer / wer`
- `latencyMs` (`p50/p90/max`)
- `topErrors` (debug samples)

Leaderboard fields:
- columns: `ocr_cer`, `ocr_exact_match_rate`, `ocr_coverage`, `ocr_latency_p90`
- filters: `max_ocr_cer`, `min_ocr_exact_match_rate`, `min_ocr_coverage`, `max_ocr_latency_p90`
- sort: `sort=ocr_cer|ocr_exact_match_rate|ocr_coverage|ocr_latency_p90`

Reference OCR HTTP chain (Gateway -> inference_service -> reference_ocr_service):

```powershell
# terminal 1: reference ocr service
python -m uvicorn services.reference_ocr_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19251

# terminal 2: inference_service (ocr provider=http -> reference ocr service)
$env:BYES_SERVICE_OCR_PROVIDER="http"
$env:BYES_SERVICE_OCR_ENDPOINT="http://127.0.0.1:19251/ocr"
$env:BYES_SERVICE_OCR_MODEL_ID="reference-ocr-v1"
python -m uvicorn services.inference_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19120

# terminal 3: Gateway replay/report with ocr enabled
cd Gateway
$env:BYES_ENABLE_OCR="1"
$env:BYES_OCR_BACKEND="http"
$env:BYES_OCR_HTTP_URL="http://127.0.0.1:19120/ocr"
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_ocr_gt_min --reset
python scripts/report_run.py --run-package tests/fixtures/run_package_with_ocr_gt_min
```

## SLAM Pose (mock/http)

Enable SLAM pose event emission in Gateway:

```powershell
cd Gateway
$env:BYES_ENABLE_SLAM="1"
$env:BYES_SLAM_BACKEND="mock"   # or http
$env:BYES_SLAM_MODEL_ID="mock-slam-v1"
# when using http backend:
# $env:BYES_SLAM_HTTP_URL="http://127.0.0.1:19120/slam/pose"
```

Expected evidence:
- `events/events_v1.jsonl` contains `name="slam.pose"` with payload `trackingState`, `pose`, `backend`, `model`, `endpoint`.
- `report.json -> inference.slam` is inferred from `slam.pose`.
- `report.json -> quality.slam` includes `trackingRate`, `lostRate`, `relocalizedCount`, `longestLostStreak`, `coverage`, `latencyMs`.

SLAM stability evaluation:

```powershell
python scripts/report_run.py --run-package tests/fixtures/run_package_with_slam_pose_gt_min
python scripts/run_regression_suite.py --suite regression/suites/contract_suite.json --baseline regression/baselines/baseline.json --fail-on-drop
```

Leaderboard fields:
- columns: `slam_tracking_rate`, `slam_lost_rate`, `slam_relocalized`, `slam_latency_p90`
- filters: `min_slam_tracking_rate`, `max_slam_lost_rate`, `max_slam_latency_p90`
- sort: `sort=slam_tracking_rate|slam_lost_rate|slam_latency_p90`

Reference SLAM HTTP chain (Gateway -> inference_service -> reference_slam_service):

```powershell
# terminal 1: reference slam service
python -m uvicorn services.reference_slam_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19261

# terminal 2: inference_service (slam provider=http -> reference slam service)
$env:BYES_SERVICE_SLAM_PROVIDER="http"
$env:BYES_SERVICE_SLAM_ENDPOINT="http://127.0.0.1:19261/slam/pose"
$env:BYES_SERVICE_SLAM_MODEL_ID="reference-slam-v1"
python -m uvicorn services.inference_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19120

# terminal 3: Gateway replay/report with slam enabled
cd Gateway
$env:BYES_ENABLE_SLAM="1"
$env:BYES_SLAM_BACKEND="http"
$env:BYES_SLAM_HTTP_URL="http://127.0.0.1:19120/slam/pose"
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_slam_pose_gt_min --reset
python scripts/report_run.py --run-package tests/fixtures/run_package_with_slam_pose_gt_min
```

Seg prompt budget sweep (local tooling, not CI gate):

```powershell
python scripts/sweep_seg_prompt_budget.py --run-package tests/fixtures/run_package_with_seg_prompt_budget_min --max-chars 64,128,256 --mode targets_text_boxes_points
```

Outputs:
- `%TEMP%\byes_seg_prompt_budget\latest.json`
- `%TEMP%\byes_seg_prompt_budget\latest.md`

Seg context pack (budgeted) from existing `seg.segment` events:

```powershell
curl "http://127.0.0.1:8000/api/seg/context?runId=<run_id>&maxChars=512&maxSegments=16&mode=topk_by_score"
```

Response is `seg.context.v1`:
- `budget`: applied budget (`maxChars/maxSegments/mode`)
- `stats.in/out/truncation`: retained vs dropped segment/text counts
- `text.promptFragment`: concise segmentation summary that can be appended to planner prompts

`report.json` also includes `segContext` (for leaderboard/regression visibility).

Plan context pack (risk+pov+seg, budgeted):

```powershell
# default budget from env/runtime defaults
curl "http://127.0.0.1:8000/api/plan/context?runId=<run_id>"

# per-request override (v4.56)
curl "http://127.0.0.1:8000/api/plan/context?runId=<run_id>&ctxMaxChars=512&ctxMode=pov_plus_risk"
```

Notes:
- `budgetOverrideUsed=true` appears only in `/api/plan/context` API response for convenience.
- `plan.context_pack` event payload remains `plan.context_pack.v1` contract-compatible (no extra override field).

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

Per-request plan context pack override during plan generation (v4.56):

```powershell
curl -X POST "http://127.0.0.1:8000/api/plan" `
  -H "Content-Type: application/json" `
  -d '{"runPackage":"Gateway/tests/fixtures/run_package_with_risk_gt_and_pov_min","frameSeq":2,"budget":{"maxChars":2000,"maxTokensApprox":256,"mode":"decisions_plus_highlights"},"constraints":{"allowConfirm":true,"allowHaptic":false,"maxActions":3},"contextPackOverride":{"maxChars":512,"mode":"pov_plus_risk"}}'
```

SafetyKernel guardrails:
- `critical`: injects `stop` when missing and forces non-stop actions to `requiresConfirm=true`.
- `high`: forces `requiresConfirm=true` for actions that were not gated.
- trims actions to `constraints.maxActions` and fills default `ttlMs=2000` when absent.

Audit outputs:
- `events/events_v1.jsonl`: appends `plan.generate` and `safety.kernel` events (and `plan.execute` when using `/api/plan/execute`).
- `report.json`: check `plan` for `riskLevel`, action counts/types, and `guardrailsApplied`.
- leaderboard (`/api/run_packages`, `/runs`): `plan_present`, `plan_risk_level`, `plan_actions`, `plan_guardrails`.

Plan context pack sweep helper (local tooling, not CI gate):

```powershell
python scripts/sweep_plan_context_pack.py `
  --run-package tests/fixtures/run_package_with_risk_gt_and_pov_min `
  --budgets 128,256,512 `
  --modes seg_plus_pov_plus_risk,pov_plus_risk,risk_only
```

Outputs:
- `%TEMP%\\byes_plan_ctx_sweep\\latest.json`
- `%TEMP%\\byes_plan_ctx_sweep\\latest.md`

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

Prompt version notes:
- `v1`: POV context only (existing behavior).
- `v2`: includes `segContext.text.promptFragment` when available; if no seg context, behavior remains identical to `v1`.

Traceability fields:
- `events/events_v1.jsonl` (`plan.generate`): `plannerProvider`, `promptVersion`, `fallbackUsed`, `fallbackReason`, `jsonValid`
- `events/events_v1.jsonl` (`plan.request`): `schemaVersion=byes.plan_request.v1`, context-inclusion/char/truncation stats
- `events/events_v1.jsonl` (`plan.rule_applied`): deterministic seg-hint rule hit with `hazardHint` + `matchedKeywords`
- `report.json` (`plan.planner.*`, `planQuality.*`): fallback and JSON validity state
- `report.json` (`planRequest`, `planEval.ruleAppliedCount`): request-budget and rule-hit aggregate metrics
- `/api/run_packages`: `plan_fallback_used`, `plan_json_valid`, `plan_prompt_version`

Planner HTTP request contract (v4.53):
- `Gateway/contracts/byes.plan_request.v1.json`
- includes `risk + contexts.pov + contexts.seg + meta.promptVersion`

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

## Frame User E2E (Capture -> Feedback)

v4.59 adds capture/ack latency tracking to make true user-perceived E2E visible:
- `frame.input` event (`frame.input.v1`): capture timestamp from device + gateway receive timestamp.
- `frame.ack` event (`frame.ack.v1`): device feedback ACK (`tts|overlay|haptic|any`), where `overlay` is treated as AR feedback in reports.
- `frame.user_e2e` event (`frame.e2e.v1` payload): `totalMs = feedbackTsMs - t0`.

v4.60 adds kind buckets and Unity wiring:
- `report.json.frameUserE2E.byKind.{tts,ar,haptic,other}` with `p50/p90/p99/max`.
- `report.json.frameUserE2E.tts` (TTFA-equivalent bucket summary).
- `/api/run_packages` columns: `frame_user_e2e_tts_p90`, `frame_user_e2e_tts_max`, `frame_user_e2e_ar_p90`, `frame_user_e2e_ar_max`, `ack_kind_diversity`.
- Unity runtime bootstrap (no scene edit): `Assets/Scripts/BYES/Telemetry/ByesFrameTelemetry.cs`.

Minimal API flow:

```powershell
# 1) upload/process frame (capture timestamp can be in meta or form field captureTsMs)
curl -X POST "http://127.0.0.1:8000/api/frame" `
  -F "image=@Gateway/tests/fixtures/run_package_with_frame_user_e2e_min/frames/frame_1.png" `
  -F "meta={\"runId\":\"demo-user-e2e\",\"frameSeq\":1,\"captureTsMs\":1713002000000,\"runPackage\":\"Gateway/tests/fixtures/run_package_with_frame_user_e2e_min\"}"

# 2) ACK when user feedback is rendered/played
curl -X POST "http://127.0.0.1:8000/api/frame/ack" `
  -H "Content-Type: application/json" `
  -d "{\"runId\":\"demo-user-e2e\",\"frameSeq\":1,\"feedbackTsMs\":1713002000120,\"kind\":\"tts\",\"accepted\":true,\"runPackage\":\"Gateway/tests/fixtures/run_package_with_frame_user_e2e_min\"}"
```

Report and leaderboard fields:
- `report.json.frameUserE2E.totalMs.{p50,p90,max}`
- `report.json.frameUserE2E.byKind.<kind>.totalMs.{p50,p90,max}`
- `report.json.frameUserE2E.tts.{p50,p90,max}`
- `report.json.frameUserE2E.coverage.ratio` (ACK coverage)
- `/api/run_packages`: `frame_user_e2e_p90`, `frame_user_e2e_max`, `frame_user_e2e_tts_p90`, `frame_user_e2e_ar_p90`, `ack_kind_diversity`, `ack_coverage`

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

## Model/Artifact Manifest (`/api/models`)

Use this to answer "what artifacts/env/endpoints are required on this machine right now?".

- API:
  - `GET /api/models`
  - returns `byes.models.v1` with per-component provider/model/endpoint + required/optional dependencies.
- CLI self-check:
  - `python Gateway/scripts/verify_models.py --json`
  - `python Gateway/scripts/verify_models.py --check --quiet`

Interpretation:
- `missingRequiredTotal == 0`: all enabled components are configured.
- `missingRequiredTotal > 0`: one or more enabled components are missing required env/file/endpoint configuration.
- `provider=mock`: component is enabled but does not require real model artifacts.
