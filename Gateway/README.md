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
- `POST /api/fault/set`
- `POST /api/fault/clear`
- `POST /api/dev/reset`
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

Low-cardinality skip reasons used by scheduler/report include:
`safe_mode`, `degraded`, `disconnect`, `ttl_expired`, `max_inflight`, `policy`.

## External Inference Service (Minimal)

Run local mock service (returns bbox/class/conf, configurable delay):

```bash
cd Gateway/external/real_det_service
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 9001
```

Optional Docker:

```bash
cd Gateway/external/real_det_service
docker build -t byes-real-det:dev .
docker run --rm -p 9001:9001 byes-real-det:dev
```

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

## Replay / Record / Assert

1. Record baseline WS events:

```bash
python scripts/ws_record_events.py --ws-url ws://127.0.0.1:8000/ws/events --output artifacts/baseline.jsonl --duration-sec 30
```

2. Replay frame directory:

```bash
python scripts/replay_send_frames.py --dir fixtures/frames --base-url http://127.0.0.1:8000 --interval-ms 500
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

RealDet baseline (requires gateway started with `BYES_ENABLE_REAL_DET=1` and det service up):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/make_report.ps1 -RealDetBaseline
```

Timeout regression example:

```powershell
curl -X POST http://127.0.0.1:8000/api/fault/set -H "Content-Type: application/json" -d "{\"tool\":\"mock_risk\",\"mode\":\"timeout\",\"value\":true}"
powershell -ExecutionPolicy Bypass -File scripts/make_report.ps1 -RunName run_timeout
curl -X POST http://127.0.0.1:8000/api/fault/clear
```

## Tests

```bash
cd Gateway
python -m pytest -q
```

Includes requested regressions:

- `test_ws_no_client_should_not_safemode`
- `test_fault_timeout_triggers_degrade`
- `test_ttl_drop_never_emit`
