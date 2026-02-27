# SECURITY_REVIEW

> Evidence-based security posture summary for maintainers.

## Current Default Assumption

Project commands and scripts remain localhost-first (`127.0.0.1`) by default:

- `docs/English/COMMANDS.md` gateway/inference examples (`--host 127.0.0.1`)
- `Gateway/scripts/dev_up.py` default `--host 127.0.0.1`

Conclusion: default profile is still local/trusted-network development.

## v4.89 Security/Hardening Additions

The repository now includes an explicit profile-driven hardening layer:

- `BYES_GATEWAY_PROFILE=local|hardened`
- Hardened defaults are injected in `Gateway/main.py` (`_apply_gateway_profile_defaults`):
  - enable rate-limit middleware
  - enable request-size limits
  - disable dev endpoints
  - disable run-package upload
  - disable arbitrary local-path run-package input

HTTP middleware order is currently `API-key/host/origin guard -> rate-limit -> request-size` (auth-first), implemented by middleware registration order in `Gateway/main.py`.

Rate-limit and body-size scope details (for predictable operations):
- Rate-limit middleware skips `/api/health`, `/api/external_readiness`, and `/metrics`, and skips `OPTIONS`.
- Request-size middleware skips `GET/HEAD/OPTIONS`, and applies per-path limits to `/api/frame*`, `/api/run_package/upload`, and other JSON write routes.
- Evidence: `Gateway/byes/middleware/rate_limit.py` (`_skip_paths`, method checks), `Gateway/byes/middleware/request_size_limit.py` (`_resolve_limit`).

## Exposed Surface and Guardrails (Code Evidence)

| Surface | Current State | Evidence |
|---|---|---|
| AuthN/AuthZ on HTTP | Optional API key guard (`BYES_GATEWAY_API_KEY`), default disabled | `Gateway/main.py` (`_gateway_guardrails`) |
| AuthN/AuthZ on WebSocket | Optional API key guard for `/ws/events` via query/header, default disabled | `Gateway/main.py` (`_ws_guardrails_ok`, `_websocket_api_key`) |
| Host/origin allowlist | Optional allowlists (`BYES_GATEWAY_ALLOWED_HOSTS`, `BYES_GATEWAY_ALLOWED_ORIGINS`) | `Gateway/main.py` (`_gateway_guardrails`, `_ws_guardrails_ok`) |
| Rate limit | Optional middleware (`BYES_GATEWAY_RATE_LIMIT_*`), hardened default enabled | `Gateway/byes/middleware/rate_limit.py`; `Gateway/main.py` middleware mount |
| Request body size limits | Optional middleware (`BYES_GATEWAY_MAX_*_BYTES`), hardened default enabled | `Gateway/byes/middleware/request_size_limit.py`; `Gateway/main.py` middleware mount |
| Dev endpoints (`/api/mock_event`, `/api/dev/*`, `/api/fault/*`) | Toggleable (`BYES_GATEWAY_DEV_ENDPOINTS_ENABLED`), hardened default disabled | `Gateway/main.py` (`_ensure_dev_endpoints_enabled`) |
| Run package upload (`/api/run_package/upload`) | Toggleable (`BYES_GATEWAY_RUNPACKAGE_UPLOAD_ENABLED`), hardened default disabled | `Gateway/main.py` (`_ensure_runpackage_upload_enabled`) |
| Local path input for context APIs | Toggleable (`BYES_GATEWAY_ALLOW_LOCAL_RUNPACKAGE_PATH`), hardened default disabled | `Gateway/main.py` (`_resolve_context_run_package_input`) |
| Mode profile config | Non-secret tuning knobs only (`BYES_MODE_PROFILE_JSON`, `BYES_EMIT_MODE_PROFILE_DEBUG`) | `Gateway/byes/config.py`; `Gateway/byes/mode_state.py`; `Gateway/main.py` |
| Zip extraction | Path traversal-safe extraction helper in use | `Gateway/scripts/report_run.py` (`safe_extract_zip`) |
| External service bind | Some Dockerfiles still bind `0.0.0.0` | `Gateway/external/*/Dockerfile` |

## Risk Notes

1. Default profile still prioritizes developer convenience; API key and guardrails are opt-in unless `hardened` is selected.
2. In-process rate-limit is per process (not distributed); deployment behind multiple workers still needs edge controls.
3. Built-in guards reduce exposure but do not replace reverse proxy auth/TLS, WAF, and centralized observability.
4. Upload and model inference endpoints remain potentially expensive even with body-size/rate limits if exposed publicly.
5. Mode profile JSON is not credential material, but malformed profile values can change compute load profile; keep it under deployment config control.

## Recommended Baseline Profiles

### Local / Intranet

- Keep `BYES_GATEWAY_PROFILE=local`
- Bind to `127.0.0.1`
- Enable `BYES_GATEWAY_API_KEY` for shared-LAN demos

### Internet-facing

- Set `BYES_GATEWAY_PROFILE=hardened`
- Explicitly set `BYES_GATEWAY_API_KEY`
- Keep `BYES_GATEWAY_ALLOWED_HOSTS`/`BYES_GATEWAY_ALLOWED_ORIGINS` strict
- Deploy behind reverse proxy with TLS + authentication + additional rate limiting
- Add body-size and timeout limits at proxy layer too (defense-in-depth)
