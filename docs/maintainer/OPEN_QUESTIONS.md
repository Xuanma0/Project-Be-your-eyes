# OPEN_QUESTIONS

## Resolved Facts (Evidence-backed)

### 1) Default Unity entry scene
- Fact: enabled BuildSettings scene is `Assets/Scenes/SampleScene.unity`.
- Evidence: `ProjectSettings/EditorBuildSettings.asset` (`enabled: 1` entry).

### 2) Demo scene availability
- Fact: `Assets/Scenes/DemoScene.unity` exists and contains same WS default URL.
- Evidence: `Assets/Scenes/DemoScene.unity:972` (`ws://127.0.0.1:8000/ws/events`).

### 3) Version head signal
- Fact: HEAD subject includes `v4.87`.
- Evidence: `git show -s --format=%s HEAD`.

### 4) Planner key variable compatibility
- Fact: planner openai mode now supports `BYES_PLANNER_LLM_API_KEY` (preferred) and `OPENAI_API_KEY` (fallback).
- Evidence: `Gateway/services/planner_service/app.py:500-505`.
- Fact: model manifest requirement now accepts either key.
- Evidence: `Gateway/byes/model_manifest.py:317-320`.

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
- Confirmed facts: `.gitignore` keeps `Assets/**/*.meta` tracked (`.gitignore:17`).
- Need decision: enforce CI/pre-commit check for missing `.meta` files?
- Recommendation: enforce `.meta` completeness checks to avoid GUID/reference drift.

### D) ASR roadmap
- Confirmed facts: repository includes TTS output components (`SpeechOrchestrator`, `AndroidTtsBackend`), but no ASR input pipeline evidence.
- Need decision: local ASR vs cloud ASR, privacy constraints, and API integration point.
- Recommendation: define ASR scope in roadmap before adding interfaces.

### E) Internet deployment profile
- Confirmed facts: default docs use localhost; external Dockerfiles bind `0.0.0.0`; app-level auth not present.
- Need decision: official supported deployment profile (local-only vs hardened internet profile).
- Recommendation: declare local/intranet as default and provide separate hardened deployment guide for internet-facing use.

### F) Final key naming policy
- Confirmed facts: compatibility exists for both planner key names.
- Need decision: whether to fully deprecate `OPENAI_API_KEY` in favor of `BYES_PLANNER_LLM_API_KEY`.
- Recommendation: publish deprecation window and keep fallback only for migration period.
