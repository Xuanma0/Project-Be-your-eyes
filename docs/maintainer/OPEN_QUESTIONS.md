# OPEN_QUESTIONS

## Resolved Facts (Evidence-backed)

### 1) Default Unity entry scene
- Fact: enabled BuildSettings scene is `Assets/Scenes/SampleScene.unity`.
- Evidence: `ProjectSettings/EditorBuildSettings.asset` (`enabled: 1` entry).

### 2) Demo scene availability
- Fact: `Assets/Scenes/DemoScene.unity` exists and contains same WS default URL.
- Evidence: `Assets/Scenes/DemoScene.unity:972` (`ws://127.0.0.1:8000/ws/events`).

### 3) Version head signal
- Fact: current development version file is `v4.90`.
- Evidence: `VERSION`.

### 4) Planner key variable compatibility
- Fact: planner openai mode now supports `BYES_PLANNER_LLM_API_KEY` (preferred) and `OPENAI_API_KEY` (fallback).
- Evidence: `Gateway/services/planner_service/app.py:500-505`.
- Fact: model manifest requirement now accepts either key.
- Evidence: `Gateway/byes/model_manifest.py:317-320`.

### 5) Gateway optional guardrails
- Fact: optional Gateway API key guard exists (`BYES_GATEWAY_API_KEY`) for HTTP + WS.
- Evidence: `Gateway/main.py` (`_gateway_guardrails`, `_ws_guardrails_ok`).
- Fact: optional host/origin allowlist exists (`BYES_GATEWAY_ALLOWED_HOSTS`, `BYES_GATEWAY_ALLOWED_ORIGINS`).
- Evidence: `Gateway/main.py` (`_gateway_guardrails`, `_ws_guardrails_ok`).
- Fact: local one-command startup script exists (`Gateway/scripts/dev_up.py`), default host is localhost.
- Evidence: `Gateway/scripts/dev_up.py` (`--host` default `127.0.0.1`).
- Fact: profile-driven hardening is now implemented (`BYES_GATEWAY_PROFILE=local|hardened`), including rate-limit/body-size/dev/upload/local-path guards.
- Evidence: `Gateway/main.py` (`_apply_gateway_profile_defaults`, middleware mount, endpoint/path guards); `Gateway/byes/config.py` (`BYES_GATEWAY_*`); `Gateway/byes/middleware/*.py`.

### 6) Mode switch caller + runtime effect
- Fact: Unity now has an in-repo `/api/mode` caller path.
- Evidence: `Assets/Scripts/BYES/Core/ByesModeManager.cs` (`PostModeChange`), `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs` (`PostModeChange`).
- Fact: Gateway now stores mode state and applies mode-profile stride at frame inference scheduling.
- Evidence: `Gateway/byes/mode_state.py`; `Gateway/main.py` (`_resolve_mode_for_frame`, `_run_inference_for_frame`, `mode_change`); `Gateway/byes/scheduler.py` (`should_run_mode_target`).

## Unresolved Decisions + Recommendation

### A) Version authority (single source of truth)
- Confirmed facts: no git tags at precheck; docs still carry historical ranges (`v4.38 -> v4.82`).
- Need decision: should release authority be `VERSION` file, git tags, or both?
- Recommendation: `VERSION` as current-dev truth + annotated git tags for releases + release notes for history.

### B) SampleScene vs DemoScene default runtime policy
- Confirmed facts: SampleScene enabled in build; DemoScene present but not enabled.
- Need decision: should DemoScene be enabled as alternative starter?
- Recommendation: keep SampleScene as default; document DemoScene as optional diagnostic/demo scene.

### C) Unity `.meta` management strategy
- Confirmed facts: `.gitignore` keeps `Assets/**/*.meta` tracked (`.gitignore:17`), and CI now runs `python tools/check_unity_meta.py` with `tools/unity_meta_allowlist.txt` for legacy gaps.
- Need decision: whether to also enforce this guard in local pre-commit hooks (in addition to CI).
- Recommendation: keep CI guard mandatory and add optional pre-commit hook template for faster local feedback.

### D) ASR roadmap
- Confirmed facts: repository includes TTS output components (`SpeechOrchestrator`, `AndroidTtsBackend`), but no ASR input pipeline evidence.
- Need decision: local ASR vs cloud ASR, privacy constraints, and API integration point.
- Recommendation: define ASR scope in roadmap before adding interfaces.

### G) Mode profile governance
- Confirmed facts: `BYES_MODE_PROFILE_JSON` can shift per-target compute cadence by mode, and `BYES_EMIT_MODE_PROFILE_DEBUG` can emit debug events.
- Need decision: should project ship one canonical production profile JSON (tracked in repo) or keep profiles deployment-local only?
- Recommendation: publish one baseline profile in docs/examples and keep deployment override capability.

### E) Internet deployment profile
- Confirmed facts: explicit `hardened` profile now exists and is documented in README + maintainer docs; default docs still use localhost; external Dockerfiles still include `0.0.0.0`.
- Need decision: should CI/release pipeline enforce hardened profile checks as release gate for internet-facing distributions?
- Recommendation: keep `local` as default dev profile; keep `hardened` as explicit opt-in baseline and publish reverse-proxy auth/TLS reference deployment.

### F) Final key naming policy
- Confirmed facts: compatibility exists for both planner key names.
- Need decision: whether to fully deprecate `OPENAI_API_KEY` in favor of `BYES_PLANNER_LLM_API_KEY`.
- Recommendation: publish deprecation window and keep fallback only for migration period.
