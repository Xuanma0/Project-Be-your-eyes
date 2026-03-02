# CONFIG_MATRIX

> This file tracks key runtime environment variables for Gateway/services and their operational impact.

## Core Runtime Toggles

| Variable | Purpose | Default | Module | Evidence |
|---|---|---|---|---|
| `BYES_OCR_BACKEND` | OCR backend selector (`mock`/`http` etc.) | `mock` | Gateway inference config | `Gateway/byes/config.py:469` |
| `BYES_RISK_BACKEND` | Risk backend selector | `mock` | Gateway inference config | `Gateway/byes/config.py:470` |
| `BYES_SEG_BACKEND` | Segmentation backend selector | `mock` | Gateway inference config | `Gateway/byes/config.py:471` |
| `BYES_DEPTH_BACKEND` | Depth backend selector | `mock` | Gateway inference config | `Gateway/byes/config.py:472` |
| `BYES_DET_BACKEND` | Detection backend selector | `mock` | Gateway inference config | `Gateway/byes/config.py` (`inference_det_backend`) |
| `BYES_SLAM_BACKEND` | SLAM backend selector | `mock` | Gateway inference config | `Gateway/byes/config.py:473` |
| `BYES_SERVICE_OCR_ENDPOINT` | OCR service endpoint | `http://127.0.0.1:9001/ocr` | Gateway inference config | `Gateway/byes/config.py:476` |
| `BYES_RISK_HTTP_URL` | Risk HTTP endpoint | `http://127.0.0.1:9002/risk` | Gateway inference config | `Gateway/byes/config.py:478` |
| `BYES_SEG_HTTP_URL` | Seg HTTP endpoint | `http://127.0.0.1:9003/seg` | Gateway inference config | `Gateway/byes/config.py:479` |
| `BYES_DEPTH_HTTP_URL` | Depth HTTP endpoint | `http://127.0.0.1:9004/depth` | Gateway inference config | `Gateway/byes/config.py:480` |
| `BYES_DET_HTTP_URL` | DET HTTP endpoint | `http://127.0.0.1:9006/det` | Gateway inference config | `Gateway/byes/config.py` (`inference_det_http_url`) |
| `BYES_SLAM_HTTP_URL` | SLAM HTTP endpoint | `http://127.0.0.1:9005/slam/pose` | Gateway inference config | `Gateway/byes/config.py:481` |
| `GATEWAY_SEND_ENVELOPE` | WS payload mode: envelope vs legacy | `false` | Gateway WS emitter | `Gateway/byes/config.py:344`, `Gateway/main.py:1695-1699` |
| `BYES_INFERENCE_EMIT_WS_V1` | Directly emit `byes.event.v1` rows to WS | `false` | Gateway inference event bridge | `Gateway/byes/config.py:559`, `Gateway/main.py:737-744` |
| `BYES_GATEWAY_API_KEY` | Optional Gateway API key guard (`X-BYES-API-Key` for HTTP, `api_key` for WS query) | empty (disabled) | Gateway HTTP middleware + WS gate | `Gateway/main.py` (`_gateway_guardrails`, `_ws_guardrails_ok`) |
| `BYES_GATEWAY_ALLOWED_HOSTS` | Optional host allowlist (comma-separated) | empty (disabled) | Gateway HTTP middleware + WS gate | `Gateway/main.py` (`_gateway_guardrails`, `_ws_guardrails_ok`) |
| `BYES_GATEWAY_ALLOWED_ORIGINS` | Optional origin allowlist (comma-separated, only when Origin header exists) | empty (disabled) | Gateway HTTP middleware + WS gate | `Gateway/main.py` (`_gateway_guardrails`, `_ws_guardrails_ok`) |
| `BYES_GATEWAY_PROFILE` | Gateway deployment profile (`local` or `hardened`) controlling default hardening behavior | `local` | Gateway profile bootstrap | `Gateway/byes/config.py:355`; `Gateway/main.py:1760-1821` |
| `BYES_GATEWAY_DEV_ENDPOINTS_ENABLED` | Toggle dev endpoints (`/api/mock_event`, `/api/dev/*`, `/api/fault/*`) | `1` in local profile, `0` default in hardened | Gateway endpoint guards | `Gateway/byes/config.py:356`; `Gateway/main.py:1955-1960` |
| `BYES_GATEWAY_RUNPACKAGE_UPLOAD_ENABLED` | Toggle `/api/run_package/upload` | `1` in local profile, `0` default in hardened | Gateway upload guard | `Gateway/byes/config.py:357`; `Gateway/main.py:1961-1965`, `2385` |
| `BYES_GATEWAY_ALLOW_LOCAL_RUNPACKAGE_PATH` | Toggle whether context APIs accept arbitrary local path inputs | `1` in local profile, `0` default in hardened | Gateway context path resolver | `Gateway/byes/config.py:358`; `Gateway/main.py:1967-1968`, `4239-4246` |
| `BYES_GATEWAY_MAX_FRAME_BYTES` | Request body max size for `/api/frame*` | `0` (disabled) in local profile, `10485760` default in hardened | Request size middleware | `Gateway/byes/config.py:359`; `Gateway/byes/middleware/request_size_limit.py` |
| `BYES_GATEWAY_MAX_RUNPACKAGE_ZIP_BYTES` | Request body max size for `/api/run_package/upload` | `0` (disabled) in local profile, `209715200` default in hardened | Request size middleware | `Gateway/byes/config.py:360`; `Gateway/byes/middleware/request_size_limit.py` |
| `BYES_GATEWAY_MAX_JSON_BYTES` | Request body max size for other JSON POST/PUT/PATCH routes | `0` (disabled) in local profile, `1048576` default in hardened | Request size middleware | `Gateway/byes/config.py:361`; `Gateway/byes/middleware/request_size_limit.py` |
| `BYES_GATEWAY_RATE_LIMIT_ENABLED` | Enable in-process rate limit middleware | `false` in local profile, `true` default in hardened | Rate limit middleware | `Gateway/byes/config.py:362`; `Gateway/byes/middleware/rate_limit.py`; `Gateway/main.py:1834-1840` |
| `BYES_GATEWAY_RATE_LIMIT_RPS` | Token refill rate (requests/sec) | `10` | Rate limit middleware | `Gateway/byes/config.py:363`; `Gateway/byes/middleware/rate_limit.py` |
| `BYES_GATEWAY_RATE_LIMIT_BURST` | Token bucket burst capacity | `20` | Rate limit middleware | `Gateway/byes/config.py:364`; `Gateway/byes/middleware/rate_limit.py` |
| `BYES_GATEWAY_RATE_LIMIT_KEY_MODE` | Keying mode: `ip` or `api_key_or_ip` | `ip` (local explicit default), hardened default fallback `api_key_or_ip` | Rate limit middleware key selector | `Gateway/byes/config.py:365-367`; `Gateway/main.py:1809`; `Gateway/byes/middleware/rate_limit.py` |
| `BYES_MODE_PROFILE_JSON` | Optional mode-driven per-target stride config (JSON string) | empty (disabled) | Gateway mode profile parser + inference scheduler | `Gateway/byes/config.py:370`; `Gateway/byes/mode_state.py:49`; `Gateway/main.py:520,916-1140` |
| `BYES_EMIT_MODE_PROFILE_DEBUG` | Optional debug event switch for per-frame fired/skipped targets (`mode.profile`) | `false` | Gateway inference event emitter | `Gateway/byes/config.py:371`; `Gateway/main.py:1186-1205` |
| `BYES_EMIT_NET_DEBUG` | Optional debug event emission for `/api/ping` requests (`net.ping`) | `false` | Gateway ping endpoint debug branch | `Gateway/byes/config.py`; `Gateway/main.py` (`ping`) |
| `BYES_VERSION_OVERRIDE` | Optional `/api/version` override string | empty | Gateway version endpoint helper | `Gateway/byes/version_info.py` (`read_repo_version`) |
| `BYES_GIT_SHA` | Optional build git sha surfaced in `/api/version` | empty | Gateway version endpoint helper | `Gateway/byes/version_info.py` (`get_build_info`) |
| `BYES_SERVICE_OCR_PROVIDER` | inference_service OCR provider selector (`mock|reference|http|tesseract|paddleocr`) | `mock` | inference_service OCR router | `Gateway/services/inference_service/app.py` (`_select_ocr_provider`) |
| `BYES_SERVICE_OCR_LANG` | PaddleOCR language code (`ch|en|...`) | `ch` | inference_service PaddleOCR provider | `Gateway/services/inference_service/providers/paddleocr_ocr.py` |
| `BYES_SERVICE_OCR_USE_GPU` | PaddleOCR GPU toggle | `0` | inference_service PaddleOCR provider | `Gateway/services/inference_service/providers/paddleocr_ocr.py` |
| `BYES_SERVICE_DET_PROVIDER` | inference_service DET provider selector (`mock|ultralytics`) | `mock` | inference_service DET router | `Gateway/services/inference_service/app.py` (`_select_det_provider`) |
| `BYES_SERVICE_DET_MODEL` | Ultralytics model id/path | `yolo26` | inference_service Ultralytics provider | `Gateway/services/inference_service/providers/ultralytics_det.py` |
| `BYES_SERVICE_DET_CONF` | Ultralytics confidence threshold | `0.25` | inference_service Ultralytics provider | `Gateway/services/inference_service/providers/ultralytics_det.py` |
| `BYES_SERVICE_DET_IMGSZ` | Ultralytics inference image size | `640` | inference_service Ultralytics provider | `Gateway/services/inference_service/providers/ultralytics_det.py` |
| `BYES_SERVICE_DEPTH_PROVIDER` | inference_service depth provider selector (`none|synth|onnx|midas|http`) | `none` | inference_service depth router | `Gateway/services/inference_service/app.py` (`_select_depth_provider`) |
| `BYES_SERVICE_DEPTH_ONNX_PATH` | ONNX depth model file path (required when depth provider is `onnx`) | empty | inference_service ONNX depth provider | `Gateway/services/inference_service/providers/onnx_depth.py` |
| `BYES_CAPTURE_USE_ASYNC_GPU_READBACK` | Unity capture path switch for async GPU readback | Android default `1` (fallback to sync when unsupported) | Quest frame capture pipeline | `Assets/BeYourEyes/Unity/Capture/ScreenFrameGrabber.cs` |
| `BYES_CAPTURE_TARGET_HZ` | Unity capture target hz used by Quest smoke/live defaults | `1` | Quest capture + scan controller | `Assets/BeYourEyes/Unity/Capture/ScreenFrameGrabber.cs`; `Assets/BeYourEyes/Unity/Interaction/ScanController.cs` |
| `BYES_CAPTURE_MAX_INFLIGHT` | Unity capture in-flight readback cap | `1` | Quest capture + scan controller | `Assets/BeYourEyes/Unity/Capture/ScreenFrameGrabber.cs`; `Assets/BeYourEyes/Unity/Interaction/ScanController.cs` |
| `BYES_PLANNER_PROVIDER` | Planner provider (`reference`/`llm`/`pov`) | `reference` fallback | Gateway planning | `Gateway/main.py:2582-2585` |
| `BYES_PLANNER_ENDPOINT` | Planner HTTP endpoint | `http://127.0.0.1:19211/plan` (http backend fallback) | Gateway planner backend | `Gateway/byes/planner_backends/http.py:15` |
| `BYES_PLANNER_LLM_API_KEY` | Primary LLM auth key (openai mode) | empty | planner_service + model manifest check | `Gateway/services/planner_service/app.py:500-505`; `Gateway/byes/model_manifest.py:317-320` |
| `OPENAI_API_KEY` | Compatibility fallback LLM key | empty | planner_service + model manifest check | `Gateway/services/planner_service/app.py:502`; `Gateway/byes/model_manifest.py:319-320` |

## v4.89 Profile Behavior

- `local` profile:
  - Keeps existing developer defaults (no forced rate/body limits; dev/upload/local-path features remain enabled unless explicitly turned off).
- `hardened` profile:
  - Applies defaults when env is not explicitly set: enables rate limit, enables body-size caps, disables dev endpoints/upload/local-path input.
- Evidence:
  - `Gateway/main.py` `_apply_gateway_profile_defaults` (`BYES_GATEWAY_*` defaults).
  - `Gateway/tests/test_gateway_dev_endpoints_toggle.py` and middleware unit tests validate toggle behavior.

## v4.90 Mode Profile Behavior

- `BYES_MODE_PROFILE_JSON` empty:
  - Gateway keeps legacy frame inference behavior (no extra mode-based stride throttling).
  - Evidence: `Gateway/byes/mode_state.py:50-52`, `Gateway/byes/scheduler.py:1090-1094`.
- `BYES_MODE_PROFILE_JSON` set:
  - Gateway parses per-mode/per-target `every_n_frames` and applies it in `_run_inference_for_frame`.
  - Mode changes from `/api/mode` or frame metadata update runtime mode state.
  - First frame after mode change force-triggers mode targets once (`_modeChanged` / `consume_changed_flag`).
  - Evidence: `Gateway/main.py:774-791`, `Gateway/main.py:898-1140`, `Gateway/byes/mode_state.py:161-230`.

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
