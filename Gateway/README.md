# BeYourEyes Gateway (v1.1 Hardening)

## Goals

Gateway keeps Unity legacy WS protocol by default and adds hardening:

- Safer degradation policy (`hadClientEverConnected` + disconnect grace)
- Fault injection (`/api/fault/set`, `/api/fault/clear`)
- Replay/record/assert scripts for regression
- Prometheus + OTel observability

## Endpoints

- `GET /api/health`
- `GET /api/mock_event`
- `POST /api/frame`
- `GET /api/tools`
- `GET /api/external_readiness`
- `POST /api/fault/set`
- `POST /api/fault/clear`
- `POST /api/dev/reset`
- `POST /api/dev/intent`
- `GET /metrics`
- `WS /ws/events`

Swagger: `/docs`

## Run

```bash
cd Gateway
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Default remains legacy WS JSON for Unity (`GATEWAY_SEND_ENVELOPE=0`).
Legacy WS event types now include: `risk`, `perception`, `health`, `action_plan`.
`FrameMeta` is optional; when Unity does not send meta, gateway behavior remains compatible.
Gateway never injects `FrameMeta` into legacy WS JSON payloads.
Health legacy events now also carry stable optional fields:
- `healthStatus`: `NORMAL|THROTTLED|DEGRADED|SAFE_MODE|WAITING_CLIENT`
- `healthReason`: stable token such as `critical_timeout:mock_risk`

## RealDet Tool (v1.2 mainline start)

`real_det` is a real-model integration slot tool on SLOW lane. It must run through
`ToolRegistry -> Scheduler -> Fusion -> SafetyKernel -> Degradation -> FrameTracker`.

Enable in gateway environment:

```bash
set BYES_ENABLE_REAL_DET=1
set BYES_REAL_DET_ENDPOINT=http://127.0.0.1:9001/infer
set BYES_REAL_DET_TIMEOUT_MS=600
set BYES_REAL_DET_MAX_INFLIGHT=2
set BYES_REAL_DET_QUEUE_POLICY=drop
```

`real_ocr` is an intent-triggered SLOW-lane OCR tool (`scan_text` only):

```bash
set BYES_ENABLE_REAL_OCR=1
set BYES_REAL_OCR_ENDPOINT=http://127.0.0.1:9102/infer/ocr
set BYES_REAL_OCR_TIMEOUT_MS=900
set BYES_REAL_OCR_MAX_INFLIGHT=1
set BYES_REAL_OCR_QUEUE_POLICY=drop
```

`real_depth` is a SLOW-lane depth hazard tool (sampled + cache reuse):

```bash
set BYES_ENABLE_REAL_DEPTH=1
set BYES_REAL_DEPTH_ENDPOINT=http://127.0.0.1:8012/infer
set BYES_REAL_DEPTH_TIMEOUT_MS=800
set BYES_REAL_DEPTH_MAX_INFLIGHT=1
set BYES_REAL_DEPTH_QUEUE_POLICY=drop
set BYES_REAL_DEPTH_SAMPLE_EVERY_N_FRAMES=5
```

`real_vlm` is an on-demand SLOW-lane tool (ask/qa intent only):

```bash
set BYES_REAL_VLM_URL=http://127.0.0.1:9103/infer/real_vlm
set BYES_REAL_VLM_TIMEOUT_MS=1800
set BYES_REAL_VLM_MAX_INFLIGHT=1
set BYES_REAL_VLM_QUEUE_POLICY=drop_newest
```

Optional tool allowlist:

```bash
set BYES_ENABLED_TOOLS=mock_risk,mock_ocr,real_depth
```

When set, only allowlisted tools are registered/planned.

Low-cardinality skip reasons used by scheduler/report include:
`safe_mode`, `degraded`, `disconnect`, `ttl_expired`, `max_inflight`, `policy`.

## ModelPack + External Readiness (v2.1)

ModelPack manifest lives at:

- `external/modelpack/manifest.yaml`

Pull placeholders (or real files if manifest has `url`):

```bash
cd Gateway
python scripts/pull_models.py --manifest external/modelpack/manifest.yaml --models det,ocr,depth,vlm --out-dir external/modelpack/weights
```

`det` now ships with an ONNXRuntime entry in manifest (`backend=onnxruntime`).
By default it downloads to:

- `<BYES_WEIGHTS_DIR>/<model_id>/model.onnx`
- example: `external/modelpack/weights/byes-real-det-onnx-cpu-v1/model.onnx`

If `url` is missing in manifest, script creates placeholder files and prints:

- `未配置下载源(url)，已创建占位文件`

Every external real_* service now exposes `GET /healthz`:

- response contract: `{ready, model_id, backend, version, warmed_up}`
- startup performs mock load + warmup
- env knobs: `BYES_BACKEND=mock|torch|onnx`, `BYES_MODEL_ID`, `BYES_WEIGHTS_DIR`

Gateway startup probes enabled real_* services via `/healthz`:

- ready + warmed_up => register tool
- not ready => mark tool unavailable and record `reason=unavailable`
- inspect probe snapshot via `GET /api/external_readiness`

`report_run.py` also records external readiness snapshot (`real_det` model_id/backend/ready/warmed_up)
in report markdown.

## External Inference Service (Minimal)

Run local mock service (returns bbox/class/conf, configurable delay):

```bash
cd Gateway/external/real_det_service
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 9001
```

Run ONNXRuntime backend (CPU) for real inference:

```bash
cd Gateway
python scripts/pull_models.py --models det --out-dir external/modelpack/weights
set BYES_BACKEND=onnxruntime
set BYES_MODEL_ID=byes-real-det-onnx-cpu-v1
set BYES_WEIGHTS_DIR=%CD%\\external\\modelpack\\weights
set BYES_MODEL_FILE=model.onnx
cd external/real_det_service
python -m uvicorn main:app --host 127.0.0.1 --port 9001
```

Readiness contract:
- if model file missing: `/healthz` => `ready=false`, `/infer` => `503`
- after startup warmup: `/healthz` => `ready=true`, `warmed_up=true`

Optional Docker:

```bash
cd Gateway/external/real_det_service
docker build -t byes-real-det:dev .
docker run --rm -p 9001:9001 byes-real-det:dev
```

## External OCR Service (RealOCR)

```bash
cd Gateway/external/real_ocr_service
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 9102
```

Optional Docker:

```bash
cd Gateway/external/real_ocr_service
docker build -t byes-real-ocr .
docker run --rm -p 9102:9102 byes-real-ocr
```

Dev knobs for OCR service:
- `OCR_SLEEP_MS`
- `OCR_TIMEOUT_PROB`

## External Depth Service (RealDepth)

```bash
cd Gateway/external/real_depth_service
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8012
```

Optional Docker:

```bash
cd Gateway/external/real_depth_service
docker build -t byes-real-depth .
docker run --rm -p 8012:8012 byes-real-depth
```

Dev knobs for depth service:
- `DELAY_MS`
- `FAIL_PROB`

## External VLM Service (RealVLM)

```bash
cd Gateway/external/real_vlm_service
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 9103
```

Optional Docker:

```bash
cd Gateway/external/real_vlm_service
docker build -t byes-real-vlm .
docker run --rm -p 9103:9103 byes-real-vlm
```

Dev knobs for VLM service:
- `VLM_SLEEP_MS`
- `VLM_FAIL_PROB`

Common readiness env for all external services:

- `BYES_BACKEND=mock|torch|onnx` (default `mock`)
- `BYES_MODEL_ID=<service_model_id>`
- `BYES_WEIGHTS_DIR=/models`
- `GET /healthz` must return `ready=true` and `warmed_up=true` before Gateway registers the tool

## Dev Intent API

Enable short-lived scan intent for OCR planning:

```bash
curl -X POST http://127.0.0.1:8000/api/dev/intent ^
  -H "Content-Type: application/json" ^
  -d "{\"intent\":\"scan_text\",\"durationMs\":5000}"
```

Enable short-lived ask intent for VLM planning:

```bash
curl -X POST http://127.0.0.1:8000/api/dev/intent ^
  -H "Content-Type: application/json" ^
  -d "{\"kind\":\"ask\",\"question\":\"what is in front of me?\",\"durationMs\":5000}"
```

Without `scan_text`, planner does not schedule `real_ocr`.
Without `ask`/`qa`, planner does not schedule `real_vlm`.

## FrameMeta v1.3

Gateway accepts optional frame alignment metadata (`FrameMeta`) for space/time alignment.
When metadata is missing or invalid, frame processing continues without 500.

Schema (Pydantic v2):

- `intrinsics`: `fx`, `fy`, `cx`, `cy`, `width`, `height`
- `pose.position`: `x`, `y`, `z`
- `pose.rotation`: `x`, `y`, `z`, `w`
- `frameSeq`, `deviceTsMs`, `unityTsMs`, `coordFrame`, `intrinsics`, `pose`, `note`

`/api/frame` input compatibility:

- `image/jpeg` or `application/octet-stream`: raw image bytes (legacy)
- `multipart/form-data`: `image` + optional `meta` JSON string

Meta parse failures:

- never trigger SAFE_MODE
- increment `byes_frame_meta_parse_error_total`
- emit throttled health warn (`meta_parse_error`)

Missing meta:

- increment `byes_frame_meta_missing_total`
- emit throttled health warn (`meta_missing`)

Valid meta:

- increment `byes_frame_meta_present_total`
- stored in `FrameTracker` runtime table (TTL + capacity bounded)

Azimuth alignment (minimal v1):

- when `intrinsics` exist and detection bbox exists:
- `azimuthDeg = atan((center_x - cx) / fx) * 180 / pi`
- otherwise fallback path remains unchanged.

## Fault Injection

Set fault:

```bash
curl -X POST http://127.0.0.1:8000/api/fault/set ^
  -H "Content-Type: application/json" ^
  -d "{\"tool\":\"mock_ocr\",\"mode\":\"timeout\",\"value\":true,\"durationMs\":10000}"
```

Clear all:

```bash
curl -X POST http://127.0.0.1:8000/api/fault/clear
```

Modes:

- `timeout`: always/probabilistic timeout (`value=true` or `0~1`)
- `slow`: add delay ms (`value=200`)
- `low_conf`: clamp confidence (`value=0.2`)
- `disconnect`: simulate tool unavailable (`value=true`)

## Degradation Policy (v1.1)

- `hadClientEverConnected=false` and no WS client: only health warn (`gateway_waiting_client`), no SAFE_MODE.
- If a client had connected before, and count drops to 0 longer than `BYES_WS_DISCONNECT_GRACE_MS` (default 3000ms): degrade by policy.
- Timeout-rate/backpressure/unavailable still drive `DEGRADED`/`SAFE_MODE`.
- Tool criticality (v1.3):
- critical tool timeout/error/unavailable => `SAFE_MODE`
- non-critical tool timeout/error/unavailable => `DEGRADED` only
- default critical set: `mock_risk` (`BYES_CRITICAL_TOOLS`)
- effective critical set is computed as:
`configured_critical ∩ registry_tools ∩ enabled_tools`

Stable degradation reason tokens:
- `critical_timeout:<tool>`
- `critical_error:<tool>`
- `noncritical_timeout:<tool>`
- `rate_limit:<tool_or_lane>`
- `waiting_client` (health warn only, does not change state)

## CrossCheck & Active Confirm (v1.4)

CrossCheckEngine runs in fusion/planner rule layer only (no extra tool calls):

- `vision_without_depth`: vision sees transparent-like obstacle while depth is empty/far
- `depth_without_vision`: depth sees near hazard while vision cannot explain it

When triggered:

- emits a conservative risk with `activeConfirm=true`
- patches ActionPlan to `stop/scan/confirm` in `NORMAL/DEGRADED`
- in `SAFE_MODE`, ActionPlan is still blocked by SafetyKernel (risk/health only)

New metrics:

- `byes_crosscheck_conflict_total{kind}`
- `byes_active_confirm_total{kind}`
- `byes_actionplan_patched_total{reason="crosscheck"}`

## HazardMemory & Risk Dedup (v1.5)

HazardMemory is a fusion-layer postprocess for risk events only (no extra tool calls):

- session-scoped active hazard table (`sessionId`, fallback `default`)
- dedup/cooldown suppression to avoid repeated risk spam
- grace retention (`grace_ms`) for short detection gaps
- critical bypass (for `dropoff` or near distance) to avoid over-suppression
- capacity + stale cleanup, runtime reset via `POST /api/dev/reset`

Legacy risk events remain backward compatible and now may include optional fields:

- `hazardId`
- `hazardKind`
- `hazardState` (`new|active|persisted`)

## v1.8 TTFA + Two-Stage + ActionGate

- TTFA (Time-to-first-action) is measured once per frame from `start_frame` to first emitted `risk` or `action_plan`.
- Two-stage output is enabled in fusion:
- `stage1`: earliest conservative action (`risk` or guard `action_plan`)
- `stage2`: richer slow-lane events (`perception`/richer `action_plan`)
- ActionPlan hard gate runs before final safety adjudication:
- `SAFE_MODE`: block all `action_plan`
- `DEGRADED`/`NORMAL`: patch `move`/`turn` to conservative `stop/scan/confirm`
- Legacy WS remains compatible. New optional fields:
- `seq`
- `stage` (`stage1`/`stage2`)

## Metrics

`GET /metrics` includes:

- `byes_e2e_latency_ms`
- `byes_tool_latency_ms{tool}`
- `byes_deadline_miss_total{lane}`
- `byes_safemode_enter_total`
- `byes_queue_depth{lane}`
- `byes_backpressure_drop_total{lane}`
- `byes_fault_set_total{tool,mode}`
- `byes_fault_trigger_total{tool,mode}`
- `byes_degradation_state_change_total{from_state,to_state,reason}`
- `byes_health_warn_total{status}`
- `byes_tool_cache_hit_total{tool}`
- `byes_tool_cache_miss_total{tool}`
- `byes_tool_rate_limited_total{tool}`
- `byes_frame_gate_skip_total{tool,reason}`
- `byes_frame_meta_present_total`
- `byes_frame_meta_missing_total`
- `byes_frame_meta_parse_error_total`
- `byes_hazard_emit_total{kind}`
- `byes_hazard_suppressed_total{reason}`
- `byes_hazard_active_gauge`
- `byes_hazard_persist_total{kind}`
- `byes_ttfa_ms`
- `byes_ttfa_count_total{outcome,kind}`
- `byes_actiongate_block_total{reason}`
- `byes_actiongate_patch_total{reason}`
- `byes_planner_select_total{tool,reason}`
- `byes_planner_skip_total{tool,reason}`

## v1.9 SLO Governor + TTFA Outcome

- `byes_ttfa_ms` remains delivery-only latency (only observed when first `risk` or `action_plan` is emitted).
- New strict accounting metric:
- `byes_ttfa_outcome_total{outcome,kind}`
- per-frame outcome is finalized exactly once at `complete_frame`, so run delta sum equals `frame_completed` delta.
- SLO Governor introduces performance mode without adding calls:
- mode: `NORMAL` / `THROTTLED`
- on pressure (e2e p95 / preprocess p95 / queue depth / timeout rate), planner reduces non-critical slow tools.
- safety remains unchanged: SAFE_MODE still only allows risk/health.
- New governor metrics:
- `byes_throttle_enter_total`
- `byes_throttle_state_gauge{state}`
- `byes_slo_violation_total{kind}`

`byes_frame_gate_skip_total.reason` is constrained to:
`intent_off`, `rate_limit`, `safe_mode`, `unchanged`, `ttl_risk`, `policy`.

## v2.0 PlannerV1

- Added `WorldState` short-window evidence cache (`last_det/last_depth/last_ocr/last_vlm/active_hazards`).
- PlannerV1 now chooses tools using safety gain + information gain + budget:
- `SAFE_MODE`: no slow tools.
- `THROTTLED`: disables `real_vlm`, down-samples non-critical slow tools.
- crosscheck conflicts can force next-frame `real_det`/`real_depth` under budget constraints.
- Planner diagnostics are emitted per frame in runtime meta and measured via:
- `byes_planner_select_total{tool,reason}`
- `byes_planner_skip_total{tool,reason}`
- Reason tokens are fixed for regression stability:
- `policy`, `intent`, `crosscheck`, `stale`, `throttled_skip`, `budget_skip`, `safe_mode_skip`, `degraded_skip`, `unavailable`.

## FrameGate + ToolCache (v1)

- Frame fingerprint: gateway computes `sha1(image_bytes)` on `/api/frame`.
- `real_ocr`: runs only when `intent=scan_text`; otherwise gated with `intent_off`.
- `real_det`: gated by min interval + unchanged-frame reuse.
- SAFE_MODE: gate layer also counts skip decisions (WS output still guarded by SafetyKernel/output layer).
- Cache key v1: `(tool_name, frame_fingerprint)` with exact-fingerprint reuse and max-age guard.

## Replay / Record / Assert

1. Record baseline WS events:

```bash
python scripts/ws_record_events.py --ws-url ws://127.0.0.1:8000/ws/events --output artifacts/baseline.jsonl --duration-sec 30
```

2. Replay frame directory:

```bash
python scripts/replay_send_frames.py --dir frames --base-url http://127.0.0.1:8000 --interval-ms 500
```

Replay with meta template (`--meta-json` supports JSON/JSONL):

```bash
python scripts/replay_send_frames.py --dir frames --base-url http://127.0.0.1:8000 --interval-ms 500 --meta-json scripts/meta_sample.json
```

3. Record candidate run:

```bash
python scripts/ws_record_events.py --ws-url ws://127.0.0.1:8000/ws/events --output artifacts/candidate.jsonl --duration-sec 30
```

4. Compare:

```bash
python scripts/replay_assert.py --baseline artifacts/baseline.jsonl --candidate artifacts/candidate.jsonl
```

Checks:

- Risk event count consistency
- SAFE_MODE enter count consistency
- Candidate expired-event emission (`receivedAtMs - timestampMs > ttlMs`) must be zero

## One-Click Report

Before each run, `scripts/make_report.ps1` now calls `POST /api/dev/reset`
to clear runtime state (faults/degradation/frame tracker) without resetting Prometheus counters.

Baseline:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/make_report.ps1 -RunName run_baseline
```

Optional external readiness smoke (prints all enabled real_* `/healthz` status, non-blocking for mock baseline):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/make_report.ps1 -RunName run_baseline -ExternalReadinessSmoke
```

RealDet baseline (requires gateway started with `BYES_ENABLE_REAL_DET=1` and det service up):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/make_report.ps1 -RealDetBaseline
```

RealDepth baseline (requires gateway started with `BYES_ENABLE_REAL_DEPTH=1` and depth service up):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/make_report.ps1 -RealDepthBaseline
```

RealDet ActionPlan scenario:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/make_report.ps1 -RealDetActionPlan
```

RealOCR scan-text scenario (requires `BYES_ENABLE_REAL_OCR=1` and OCR service up):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/make_report.ps1 -RunName run_realoocr_scan -RealOcrScan
```

RealVLM ask scenario (requires `BYES_REAL_VLM_URL` configured and VLM service up):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/make_report.ps1 -RunName run_real_vlm_ask -RealVlmAsk
```

PlannerV1 crosscheck scenario (forces crosscheck conflicts through dev override):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/make_report.ps1 -RunName run_planner_crosscheck_v20 -PlannerV1CrossCheck
```

PlannerV1 throttled ask scenario (forces THROTTLED + ask intent):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/make_report.ps1 -RunName run_planner_throttledask_v20 -PlannerV1ThrottledAsk
```

Queue pressure scenario (injects slow fault on `mock_ocr`, validates queue/exec latency metrics + adaptive planner skip):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/make_report.ps1 -RunName run_queue_pressure_v23 -QueuePressureScenario
```

Timeout regression examples:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/make_report.ps1 -TimeoutScenario
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts/make_report.ps1 -RunName run_realoocr_timeout -RealOcrScan -TimeoutScenario
```

Cache scenario (repeat same first frame 50 times, intent off):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/make_report.ps1 -RunName run_cache -CacheScenario
```

How to read cache scenario report:
- `frame_received/frame_completed/e2e_count` should all be `50`.
- `real_det invoked` should be much smaller than `50`.
- `real_ocr invoked` should be `0` when intent is off.
- `byes_tool_cache_hit_total{tool=real_det}` should grow.

v2.3 runtime latency metrics:
- `byes_tool_queue_ms{tool,lane}`
- `byes_tool_exec_ms{tool,lane}`
- planner adaptive skip reason: `latency_pred_exceeds_budget`

Run-package report mode (consume Unity-exported run package directly):

```bash
python scripts/report_run.py --run-package /path/to/RunPackageDir
```

Zip input is also supported:

```bash
python scripts/report_run.py --run-package /path/to/RunPackage.zip
```

Notes:
- The script reads `manifest.json` (or `run_manifest.json`) in the package dir.
- It auto-loads `wsJsonl`, `metricsBefore`, `metricsAfter` from manifest.
- Default output is `<run-package>/report.md` for directories.
- For `.zip`, default output is `report_<zip_stem>.md` beside the zip.

Batch scan and generate reports:

```bash
python scripts/report_packages.py --root /path/to/packages --out /path/to/out
```

`report_packages.py` recursively scans both run-package directories (`manifest.json`) and `.zip`,
generates per-run reports, and writes `index.md` + `index.json`.

Run package upload API (server-side report generation):

```bash
curl -X POST "http://127.0.0.1:8000/api/run_package/upload" ^
  -F "file=@run_package.zip" ^
  -F "scenarioTag=baseline"
```

Server behavior:
- saves zip to `Gateway/artifacts/run_packages/<timestamp>_<scenario>.zip`
- safely extracts to sibling directory
- generates `report.md` and `report.json`
- returns `{ ok, runDir, reportMdPath, reportJsonPath, summary }`

Meta baseline (optional FrameMeta on all frames):

1. Example `scripts/meta_sample.json`:

```json
{
  "frameMeta": {
    "coordFrame": "World",
    "deviceTsMs": 1700000000000,
    "intrinsics": {
      "fx": 560.0,
      "fy": 560.0,
      "cx": 320.0,
      "cy": 180.0,
      "width": 640,
      "height": 360
    }
  },
  "preserveOld": true,
  "ttlMs": 5000
}
```

2. Run:

```bash
python scripts/replay_send_frames.py --dir frames --base-url http://127.0.0.1:8000 --interval-ms 500 --repeat-first 50 --meta-json scripts/meta_sample.json --preserve-old
```

3. Expect:

- `frame_received=50`, `frame_completed=50`, `e2e_count=50`
- `byes_frame_meta_present_total` delta `=50`

## Tests

```bash
cd Gateway
python -m pytest -q
```

Includes requested regressions:

- `test_ws_no_client_should_not_safemode`
- `test_fault_timeout_triggers_degrade`
- `test_ttl_drop_never_emit`
- `test_real_depth_baseline_invoked`
- `test_real_depth_timeout_noncritical_no_safemode`
- `test_critical_timeout_enters_safemode`

## Unity Skeleton v2.8

Unity-side minimal closed loop scripts were added under `Assets/BeYourEyes`:

- `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs`
- `Assets/BeYourEyes/Unity/Capture/FrameCapture.cs`
- `Assets/BeYourEyes/Presenters/DebugHUD/GatewayHUD.cs`
- `Assets/BeYourEyes/Presenters/DebugHUD/DevIntentPanel.cs`

UPM dependency added in `Packages/manifest.json`:

- `com.endel.nativewebsocket` (`https://github.com/endel/NativeWebSocket.git#upm`)
- `com.unity.nuget.newtonsoft-json` (already present, used for `JObject` parsing)

Editor smoke checklist:

1. Add `GatewayClient`, `FrameCapture`, `GatewayHUD`, `DevIntentPanel` to one scene object.
2. Set Gateway URLs (`BaseUrl`, `WsUrl`) and click `Apply Gateway`.
3. Start play mode and verify console:
- `WS connected`
- recurrent `type=health` logs from WS
4. Enable frame capture (`FrameCapture autoStart=true`) and verify:
- repeated `/api/frame` HTTP 200 (client logs every N successes)
- WS receives at least one of `risk/perception/action_plan`
5. Trigger active confirm (e.g. `make_report.ps1 -ActiveConfirmScenario` or dev crosscheck override):
- WS receives `action_plan` with `confirmId`
- click option button in HUD, verify `/api/confirm` 200 and behavior update in subsequent events.
