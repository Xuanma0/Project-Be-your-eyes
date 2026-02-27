Current development version is defined by `VERSION`; this file records historical milestones only.

# Release Notes (v4.x)

This changelog summarizes delivered capabilities from `v4.38` onward for reviewers and maintainers.

## v4.93
- Fixed Unity compile break by removing `BYES` namespace dependencies from `Assets/BeYourEyes/**` (networking/capture layer).
- Added layering-safe runtime bridge (`GatewayRuntimeContext`) and BYES-side registration in runtime bootstrap.
- Added repo guard `tools/check_unity_layering.py` and CI step to prevent re-introducing `BYES` references in `Assets/BeYourEyes/**`.
- Quest3 smoke path remains supported (connection panel ping/version/mode + live loop) with build unblocked.

## v4.92
- Added Quest 3 live loop controls in Unity scan path:
  - live on/off toggle, target FPS, max in-flight backpressure, busy-drop behavior
  - default capture bandwidth controls for Quest (`maxWidth/maxHeight/jpegQuality`)
- Added Gateway diagnostics endpoint `GET /api/version` returning version/git-sha/uptime/profile.
- Added runtime panel telemetry updates for Quest smoke validation:
  - HTTP/WS status, ping RTT, last upload cost, coarse event E2E, live loop status
  - manual `Get Version` probe in panel.
- Added Gateway tests for `/api/version`, and synced maintainer docs/runbooks/config matrix.

## v4.91
- Added Quest 3 smoke-loop enablement pieces:
  - runtime connection panel for host/port/api-key config + reconnect
  - XR controller scan trigger support (right-hand primary/trigger) while keeping desktop `S` fallback
  - dedicated `Quest3SmokeScene` entry in Build Settings and runtime passthrough setup helper
- Added Gateway runtime introspection endpoints:
  - `GET /api/mode` (reads mode from mode-state store)
  - `POST /api/ping` (lightweight RTT helper)
- Added/updated tests for the new endpoints, including API-key guard behavior.
- Updated runbooks and config matrix for Quest LAN setup and new endpoint/env coverage.

## v4.90
- Added mode-synced active-perception profile support in Gateway:
  - new runtime mode state store (`Gateway/byes/mode_state.py`)
  - optional mode profile env (`BYES_MODE_PROFILE_JSON`) for per-target keyframe stride
  - optional debug event switch (`BYES_EMIT_MODE_PROFILE_DEBUG`) for per-frame fired/skipped targets
- Wired `/api/mode` into Gateway runtime mode state so mode changes affect subsequent frame inference scheduling (with one-shot force-run on mode-change frame).
- Added unit tests for mode profile parsing/fallback, mode-state store behavior (TTL/LRU/changed-flag), and scheduler stride decisions.
- Updated maintainer docs/runbook/config matrix to document mode sync and profile verification steps.

## v4.89
- Added a profile-driven Gateway hardening layer (`BYES_GATEWAY_PROFILE=local|hardened`) with hardened defaults for rate-limit, request-size limits, and dev surface restrictions.
- Added Gateway resource guardrails:
  - in-process rate limit middleware (`BYES_GATEWAY_RATE_LIMIT_*`)
  - request body size middleware (`BYES_GATEWAY_MAX_*_BYTES`)
  - dev endpoint/run-package upload/local-path guards (`BYES_GATEWAY_*_ENABLED`)
- Added CI guards for Unity `.meta` completeness and docs relative-link validation:
  - `tools/check_unity_meta.py`
  - `tools/check_docs_links.py`
- Added corresponding tests for middleware and endpoint toggles in `Gateway/tests/`.

## v4.88
- Added `Gateway/scripts/dev_up.py` for one-command local orchestration (Gateway + optional inference/planner/reference services).
- Added optional Gateway API key guard for HTTP + WebSocket (`BYES_GATEWAY_API_KEY`) and optional host/origin allowlists.
- Added API key compatibility in Unity clients and `Gateway/scripts/replay_run_package.py` (`X-BYES-API-Key` + WS `api_key` query).

## v4.38
- Planner evaluation metrics, ablation sweep (`provider/prompt/budget`), leaderboard/report integration, regression gate.

## v4.39-v4.40
- POV planner adapter (`pov.ir.v1 -> action_plan.v1`).
- Live POV ingest API + in-memory POV store + inline `povIr` planning path.

## v4.41
- Contracts freeze workflow (`Gateway/contracts/*` + `contract.lock.json`).
- `/api/contracts` + strict contract verification in suite/CI.

## v4.42-v4.44
- Segmentation provider chain (`mock/http`) and `/seg`.
- Segmentation quality metrics and GT fixture.
- Seg payload contract hardening (`byes.seg.v1`) + payload normalization checks.

## v4.45-v4.47
- `reference_seg_service` and HTTP E2E.
- Seg prompt contract (`byes.seg_request.v1`) + prompt passthrough + `seg.prompt` events.

## v4.48-v4.50
- Optional mask support in `byes.seg.v1` (`rle_v1`) + mask metrics.
- Prompt-conditioned segmentation behavior and prompt+mask contract coverage.

## v4.51-v4.52
- Prompt budget/truncation engineering for segmentation.
- Seg ContextPack (`seg.context.v1`) + `/api/seg/context` + planner prompt v2 optional inclusion.

## v4.53-v4.55
- `byes.plan_request.v1` + context-aware planner HTTP request.
- Explainable rule layer for seg hints.
- Plan-context alignment metrics (`plan.context_alignment.v1`).
- Unified PlanContextPack (`plan.context_pack.v1`) + `/api/plan/context`.

## v4.56-v4.58
- Per-request plan context pack override.
- Context sweep tool.
- Frame E2E latency contract/events (`frame.e2e.v1`) and hardening (single emit + dedupe consistency).

## v4.59-v4.60
- `frame.input.v1` + `frame.ack.v1` + capture->feedback user-E2E metrics.
- Kind-bucketed user-E2E (`tts/ar/haptic`) in reports/leaderboard.

## v4.61-v4.64
- Depth provider/toolchain (`byes.depth.v1`, reference depth service, quality metrics).
- Model manifest (`byes.models.v1`, `/api/models`, `verify_models.py`).
- OCR provider/toolchain (`byes.ocr.v1`, reference OCR service, CER/exact-match metrics).
- SLAM pose provider/toolchain (`byes.slam_pose.v1`, reference SLAM service, stability metrics).

## v4.65-v4.66
- `sam3_seg_service` (fixture/sam3 modes), downstream switching.
- `da3_depth_service` (fixture/da3 modes), downstream switching.
- Model-manifest requirements for SAM3/DA3 artifact paths.

## v4.67-v4.75
- pySLAM TUM ingestion into `slam.pose` offline events.
- Dataset importers (Ego4D video / image folder) and benchmark batch runner + matrix profiles.
- pySLAM prehooks (`pyslam_ingest`, `pyslam_run`) for benchmark workflows.
- SLAM error metrics (`ATE/RPE`) from GT TUM.
- SlamContextPack (`slam.context.v1`) + `/api/slam/context`.

## v4.76-v4.79
- SLAM context wired into plan request and planner prompt (`v3`).
- Local costmap (`byes.costmap.v1`) + costmap context (`costmap.context.v1`) + planner prompt (`v4`).
- Fused costmap (`byes.costmap_fused.v1`) with EMA/optional shift.
- Shift gate with explainable reject reasons and online/final trajectory profiles.

## v4.80-v4.81
- SAM3 tracking passthrough (`trackId`, `trackState`) and seg tracking metrics.
- Dynamic obstacle temporal filtering cache (trackId-aware) integrated into costmap/costmap_fused.

## v4.82
- DA3 ref-view strategy passthrough (`refViewStrategy`) end-to-end.
- Temporal depth consistency metrics:
  - `jitterAbs`
  - `flickerRateNear`
  - `scaleDriftProxy`
  - `refViewStrategyDiversityCount`
- Integrated into report/leaderboard/linter/contract gate/matrix summary.
