# SECURITY_REVIEW

> Evidence-based security posture summary for open-source maintainers.

## Current Default Assumption

Project documentation and run commands primarily bind to localhost (`127.0.0.1`) for Gateway/inference services:
- `docs/English/COMMANDS.md:51` (`uvicorn main:app --host 127.0.0.1 --port 8000`).
- `docs/English/COMMANDS.md:57` (`services.inference_service.app:app --host 127.0.0.1 --port 19120`).
- `Gateway/scripts/dev_up.py` defaults to `--host 127.0.0.1`.

Conclusion: default operational assumption is local machine / trusted LAN, not internet-exposed deployment.

## Exposed Surface (Code Evidence)

| Surface | Current State | Evidence |
|---|---|---|
| AuthN/AuthZ on Gateway APIs | Optional API key middleware exists (`BYES_GATEWAY_API_KEY`), default disabled | `Gateway/main.py` (`_gateway_guardrails`) |
| WS auth on `/ws/events` | Optional key check via query/header exists, default disabled | `Gateway/main.py` (`_ws_guardrails_ok`, `_websocket_api_key`) |
| Host/origin allowlist | Optional allowlists (`BYES_GATEWAY_ALLOWED_HOSTS`, `BYES_GATEWAY_ALLOWED_ORIGINS`) exist, default disabled | `Gateway/main.py` (`_gateway_guardrails`, `_ws_guardrails_ok`) |
| File upload endpoint | Present: `POST /api/run_package/upload` | `Gateway/main.py:2128-2188` |
| Zip extraction | Path traversal checks present | `Gateway/scripts/report_run.py:2008-2017` (`safe_extract_zip`) |
| Path confinement (run package index paths) | Constrained to run_packages root | `Gateway/main.py:654-664` (`path escapes run_packages root`) |
| Context run package input path | Accepts arbitrary existing dir/zip path | `Gateway/main.py:3987-4003` |
| WebSocket stream | Public `/ws/events` endpoint | `Gateway/main.py:8280-8302` |
| External service container bind | `0.0.0.0` in Dockerfiles | `Gateway/external/*/Dockerfile` (e.g., real_det line 9, real_ocr line 13) |

## Risk Notes

1. If exposed publicly without reverse-proxy controls, API surface is still high-risk (built-in API-key guard is optional and off by default).
2. Optional API-key guard improves baseline but is not a full internet security profile.
3. Upload/decompress path is safer than naive unzip but still represents resource-abuse surface.
4. Accepting arbitrary local run package paths is acceptable for local tooling, risky for untrusted remote input.

## Minimum Baseline Recommendations (Repo-level)

### Local / Intranet baseline
- Keep default bind `127.0.0.1` in examples and scripts.
- For shared LAN demos, set `BYES_GATEWAY_API_KEY` and use key-aware Unity/replay clients.
- Treat `/api/run_package/upload` and `/api/dev/*` as dev-only endpoints.

### Internet-facing baseline
- Require reverse proxy with TLS + authentication (JWT/API key/mTLS).
- Apply rate-limit and request body size limits on upload endpoints.
- Restrict allowed hosts/origins at edge or app layer.
- Disable dev endpoints and local-path based inputs in production profile.
