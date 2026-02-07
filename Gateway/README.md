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

## Tests

```bash
cd Gateway
python -m pytest -q
```

Includes requested regressions:

- `test_ws_no_client_should_not_safemode`
- `test_fault_timeout_triggers_degrade`
- `test_ttl_drop_never_emit`
