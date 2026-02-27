# CONFIG_MATRIX

> This file tracks key runtime environment variables for Gateway/services and their operational impact.

## Core Runtime Toggles

| Variable | Purpose | Default | Module | Evidence |
|---|---|---|---|---|
| `BYES_OCR_BACKEND` | OCR backend selector (`mock`/`http` etc.) | `mock` | Gateway inference config | `Gateway/byes/config.py:469` |
| `BYES_RISK_BACKEND` | Risk backend selector | `mock` | Gateway inference config | `Gateway/byes/config.py:470` |
| `BYES_SEG_BACKEND` | Segmentation backend selector | `mock` | Gateway inference config | `Gateway/byes/config.py:471` |
| `BYES_DEPTH_BACKEND` | Depth backend selector | `mock` | Gateway inference config | `Gateway/byes/config.py:472` |
| `BYES_SLAM_BACKEND` | SLAM backend selector | `mock` | Gateway inference config | `Gateway/byes/config.py:473` |
| `BYES_SERVICE_OCR_ENDPOINT` | OCR service endpoint | `http://127.0.0.1:9001/ocr` | Gateway inference config | `Gateway/byes/config.py:476` |
| `BYES_RISK_HTTP_URL` | Risk HTTP endpoint | `http://127.0.0.1:9002/risk` | Gateway inference config | `Gateway/byes/config.py:478` |
| `BYES_SEG_HTTP_URL` | Seg HTTP endpoint | `http://127.0.0.1:9003/seg` | Gateway inference config | `Gateway/byes/config.py:479` |
| `BYES_DEPTH_HTTP_URL` | Depth HTTP endpoint | `http://127.0.0.1:9004/depth` | Gateway inference config | `Gateway/byes/config.py:480` |
| `BYES_SLAM_HTTP_URL` | SLAM HTTP endpoint | `http://127.0.0.1:9005/slam/pose` | Gateway inference config | `Gateway/byes/config.py:481` |
| `GATEWAY_SEND_ENVELOPE` | WS payload mode: envelope vs legacy | `false` | Gateway WS emitter | `Gateway/byes/config.py:344`, `Gateway/main.py:1695-1699` |
| `BYES_INFERENCE_EMIT_WS_V1` | Directly emit `byes.event.v1` rows to WS | `false` | Gateway inference event bridge | `Gateway/byes/config.py:559`, `Gateway/main.py:737-744` |
| `BYES_GATEWAY_API_KEY` | Optional Gateway API key guard (`X-BYES-API-Key` for HTTP, `api_key` for WS query) | empty (disabled) | Gateway HTTP middleware + WS gate | `Gateway/main.py` (`_gateway_guardrails`, `_ws_guardrails_ok`) |
| `BYES_GATEWAY_ALLOWED_HOSTS` | Optional host allowlist (comma-separated) | empty (disabled) | Gateway HTTP middleware + WS gate | `Gateway/main.py` (`_gateway_guardrails`, `_ws_guardrails_ok`) |
| `BYES_GATEWAY_ALLOWED_ORIGINS` | Optional origin allowlist (comma-separated, only when Origin header exists) | empty (disabled) | Gateway HTTP middleware + WS gate | `Gateway/main.py` (`_gateway_guardrails`, `_ws_guardrails_ok`) |
| `BYES_PLANNER_PROVIDER` | Planner provider (`reference`/`llm`/`pov`) | `reference` fallback | Gateway planning | `Gateway/main.py:2582-2585` |
| `BYES_PLANNER_ENDPOINT` | Planner HTTP endpoint | `http://127.0.0.1:19211/plan` (http backend fallback) | Gateway planner backend | `Gateway/byes/planner_backends/http.py:15` |
| `BYES_PLANNER_LLM_API_KEY` | Primary LLM auth key (openai mode) | empty | planner_service + model manifest check | `Gateway/services/planner_service/app.py:500-505`; `Gateway/byes/model_manifest.py:317-320` |
| `OPENAI_API_KEY` | Compatibility fallback LLM key | empty | planner_service + model manifest check | `Gateway/services/planner_service/app.py:502`; `Gateway/byes/model_manifest.py:319-320` |

## Service Port/Bind Variables

| Variable | Purpose | Default | Evidence |
|---|---|---|---|
| `PLANNER_SERVICE_HOST` | Planner Flask bind host | `127.0.0.1` | `Gateway/services/planner_service/app.py:775` |
| `PLANNER_SERVICE_PORT` | Planner Flask bind port | `19211` | `Gateway/services/planner_service/app.py:776` |

## OPENAI_API_KEY vs BYES_PLANNER_LLM_API_KEY

### Current state
- Compatibility fix applied:
  - `planner_service` now reads `BYES_PLANNER_LLM_API_KEY` first, then falls back to `OPENAI_API_KEY` (`Gateway/services/planner_service/app.py:500-505`).
  - `model_manifest` now accepts either key as satisfied (`Gateway/byes/model_manifest.py:317-320`).

### Residual risk
- Dual variable names still exist, so operator confusion is still possible if documentation is ignored.

### Compatibility recommendation
1. Prefer `BYES_PLANNER_LLM_API_KEY` as primary runtime variable.
2. Keep `OPENAI_API_KEY` only as backward-compatible fallback.
3. Keep docs explicit about precedence to avoid dual-source drift.

## Full Scan Note

Automated scan found `317` unique env variables across Python files (source: generated audit data from repo scan). This document lists maintainers' high-impact runtime knobs; full inventory can be regenerated from source search (`os.getenv`, `_env_*`).
