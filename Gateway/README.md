# BeYourEyes Gateway (Model Integration v1)

## Overview

This Gateway keeps the Unity-compatible endpoints and adds a model integration layer:

- Tool registry (`byes/tool_registry.py`)
- Dual-lane scheduler (`byes/scheduler.py`)
- Fusion (`byes/fusion.py`)
- Safety kernel (`byes/safety.py`)
- Degradation manager (`byes/degradation.py`)
- Observability + metrics (`byes/observability.py`, `byes/metrics.py`)

## Endpoints

- `GET /api/health`
- `GET /api/mock_event`
- `POST /api/frame` (multipart: `image`, optional `meta` json string)
- `GET /api/tools`
- `GET /metrics`
- `WS /ws/events`

Swagger is available at `/docs`.

## Local Run

```bash
cd Gateway
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

## Envelope Compatibility Switch

Default output is Unity legacy event shape.

```bash
# legacy mode (default)
set GATEWAY_SEND_ENVELOPE=0

# envelope mode
set GATEWAY_SEND_ENVELOPE=1
```

When `GATEWAY_SEND_ENVELOPE=1`, WS pushes `EventEnvelope` with legacy-compatible fields inside `payload`.

## Frame -> WS Flow

1. Unity uploads frame to `POST /api/frame`.
2. Scheduler fans out tools by lane (`FAST` risk, `SLOW` OCR-like).
3. Fusion builds risk/perception events.
4. Safety kernel applies invariants (risk preemption, TTL, low-confidence guard).
5. Final events are sent to all `/ws/events` clients.

## Safe Mode and Degradation

State machine:

- `NORMAL`
- `DEGRADED` (slow lane disabled)
- `SAFE_MODE` (risk-only)

Signals implemented in v1:

- Tool timeout rate above threshold.
- WS client disconnect/no clients (configurable via `BYES_SAFE_MODE_NO_WS`).

State transitions emit `health` events to WS.

## Key Environment Variables

- `GATEWAY_SEND_ENVELOPE` (`0` or `1`)
- `BYES_DEFAULT_TTL_MS`
- `BYES_FAST_DEADLINE_MS`
- `BYES_SLOW_DEADLINE_MS`
- `BYES_TIMEOUT_RATE_THRESHOLD`
- `BYES_TIMEOUT_WINDOW_SIZE`
- `BYES_SAFE_MODE_NO_WS`
- `BYES_MOCK_TOOL_TIMEOUT_MS`
- `BYES_MOCK_RISK_DELAY_MS`
- `BYES_MOCK_OCR_DELAY_MS`

## Metrics

Prometheus endpoint: `GET /metrics`

Provided metrics:

- `byes_e2e_latency_ms` (Histogram)
- `byes_tool_latency_ms{tool}` (Histogram)
- `byes_deadline_miss_total{lane}` (Counter)
- `byes_safemode_enter_total` (Counter)
- `byes_queue_depth{lane}` (Gauge)
- `byes_backpressure_drop_total{lane}` (Counter)

## Simulate Timeout -> Safe Mode

```bash
set BYES_MOCK_RISK_DELAY_MS=2000
set BYES_MOCK_TOOL_TIMEOUT_MS=300
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Then upload frames repeatedly to `/api/frame`. Timeouts increase, state transitions to `DEGRADED` or `SAFE_MODE`, and counters in `/metrics` rise.

## Tests

```bash
cd Gateway
pytest -q
```

Coverage includes:

- TTL drop (`tests/test_ttl_drop.py`)
- Safety rules (`tests/test_safety_kernel.py`)
- Frame-driven cancellation (`tests/test_scheduler_cancel.py`)
