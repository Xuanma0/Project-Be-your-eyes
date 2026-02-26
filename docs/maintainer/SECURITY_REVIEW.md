# SECURITY_REVIEW

> Evidence-based security posture summary for open-source maintainers.

## Current Default Assumption

Project documentation and run commands primarily bind to localhost (`127.0.0.1`) for Gateway/inference services:
- `docs/English/COMMANDS.md:51` (`uvicorn main:app --host 127.0.0.1 --port 8000`).
- `docs/English/COMMANDS.md:57` (`services.inference_service.app:app --host 127.0.0.1 --port 19120`).

Conclusion: default operational assumption is local machine / trusted LAN, not internet-exposed deployment.

## Exposed Surface (Code Evidence)

| Surface | Current State | Evidence |
|---|---|---|
| AuthN/AuthZ on Gateway APIs | No explicit auth middleware/dependency found | `Gateway/main.py` grep: `HTTPBearer/OAuth2/APIKey/CORSMiddleware/TrustedHostMiddleware` all NOT_FOUND |
| File upload endpoint | Present: `POST /api/run_package/upload` | `Gateway/main.py:2128-2188` |
| Zip extraction | Path traversal checks present | `Gateway/scripts/report_run.py:2008-2017` (`safe_extract_zip`) |
| Path confinement (run package index paths) | Constrained to run_packages root | `Gateway/main.py:654-664` (`path escapes run_packages root`) |
| Context run package input path | Accepts arbitrary existing dir/zip path | `Gateway/main.py:3987-4003` |
| WebSocket stream | Public `/ws/events` endpoint | `Gateway/main.py:8280-8302` |
| External service container bind | `0.0.0.0` in Dockerfiles | `Gateway/external/*/Dockerfile` (e.g., real_det line 9, real_ocr line 13) |

## Risk Notes

1. If exposed publicly without reverse-proxy controls, current API surface is high-risk (no built-in auth guardrails).
2. Upload/decompress path is safer than naive unzip but still represents resource-abuse surface.
3. Accepting arbitrary local run package paths is acceptable for local tooling, risky for untrusted remote input.

## Minimum Baseline Recommendations (Repo-level)

### Local / Intranet baseline
- Keep default bind `127.0.0.1` in examples and scripts.
- Add explicit warning banner in README that Gateway is unauthenticated by default.
- Treat `/api/run_package/upload` and `/api/dev/*` as dev-only endpoints.

### Internet-facing baseline
- Require reverse proxy with TLS + authentication (JWT/API key/mTLS).
- Apply rate-limit and request body size limits on upload endpoints.
- Restrict allowed hosts/origins at edge or app layer.
- Disable dev endpoints and local-path based inputs in production profile.
