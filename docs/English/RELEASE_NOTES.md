Current development version is defined by `VERSION`; this file records historical milestones only.

# Release Notes (v4.x)

This changelog summarizes delivered capabilities from `v4.38` onward for reviewers and maintainers.

## v5.08.1
- Hardened provider truth normalization so Quest Panel, Desktop Console, `/api/providers`, `/api/capabilities`, and `/api/ui/state` no longer report `real` when DET, SLAM, or other providers are enabled but currently failing; recent `503`, `404`, timeout, disabled, and missing-path conditions now resolve to `unavailable` with a visible reason.
- Stabilized Quest overlay asset lifecycle by treating overlay assets as immutable blobs: Quest only downloads when `assetId` changes, caches successful textures locally, preserves last-frame hold after success, and suppresses repeated GETs for the same failed asset id.
- Removed blank overlay layers from the whole-FOV HUD by disabling DET, SEG, and DEPTH renderers when no valid texture exists, preventing the white or red fallback-looking backgrounds that previously occluded passthrough and panel content.
- Compressed the Hand Menu interaction surface into smaller in-page sections, labeled sliders, and stronger system-gesture conflict isolation so the palm-up menu is shorter, less overlapping, and less likely to fight Meta system gestures.
- Added explicit passthrough truth reporting and fallback disable behavior so Quest and Desktop surfaces now show `Passthrough: unavailable|fallback|real` with reasons instead of leaving users in an ambiguous half-enabled visual state.

## v5.08
- Added proof-gated PCA truth across Quest panel, Desktop Console, `/api/capabilities`, `/api/providers`, and `/api/ui/state`; `pca_real` now requires supported Quest 3 or 3S hardware, non-Link runtime, camera permission, provider availability, and provider readiness at the same time.
- Hardened whole-FOV overlay rendering on Quest by keeping DET, SEG, and DEPTH in a last-frame-hold path with latest-frame-wins asset fetch behavior instead of stacking overlay downloads or chasing per-frame inference.
- Promoted Desktop Console into an operator UI on top of existing APIs by adding `Scan Once`, `Live Start/Stop`, `Read Text`, `Find Door`, and `Record Start/Stop` controls plus frame-source truth, provider truth, latest capture success, and overlay previews.
- Added explicit pySLAM realtime visibility to Quest and Desktop surfaces with `backend`, `state`, `fps`, `latency`, and `root detected` evidence while keeping pySLAM optional and outside default CI success criteria.
- Extended Quest self-test to validate capture truth, whole-FOV overlay truth, and Desktop alignment without touching contracts or inference-provider semantics.

## v5.07
- Added strict frame-source truth normalization across Quest panel, Desktop Console, `/api/capabilities`, `/api/providers`, and `/api/ui/state`; capture can now surface only `pca_real`, `ar_cpuimage_fallback`, `rendertexture_fallback`, or `unavailable`.
- Added Quest-visible voice truth evidence: mic permission state, last transcript, last spoken text, TTS muted state, and backend truth now appear on the Quest panel, hand-menu voice page, and Desktop Console.
- Extended Gateway ASR/TTS runtime evidence so `/api/providers`, `/api/ui/state`, and the Desktop Console expose `backend`, `model`, `device`, `is_mock`, `reason`, `last_success_ts`, `last_infer_ms`, transcript history, spoken history, and muted status.
- Hardened true-capture and true-voice smoke validation by adding capture-truth alignment checks to Quest self-test while keeping contracts, inference providers, recording, replay, and regression semantics unchanged.
- Preserved the v5.06 interaction boundary: no new primary Quest entry was added, pySLAM remains optional, and true-capture/true-voice evidence is layered into existing Hand Menu + Smoke Panel surfaces.

## v5.06
- Unified Quest interaction around `BYES_HandMenu` as the sole primary entry; legacy wrist menu is disabled by default and Smoke Panel is pushed back to status-summary and fallback controls.
- Normalized frame-source truth across Quest panel, Desktop Console, `/api/capabilities`, `/api/providers`, and `/api/ui/state`; fallback capture now reports `ar_cpuimage_fallback` or `rendertexture_fallback` instead of implying real PCA.
- Hardened Desktop Console runtime truth view with normalized provider evidence (`backend`, `model`, `device`, `is_mock`, `reason`, `last_success_ts`, `last_infer_ms`), current mode, recording state, target session, overlay kinds, and latest frame summary.
- Kept smoke mainline compatibility by preserving contracts and provider logic while adding truth-mapping and one-version compatibility fields where needed.
- Neutralized maintainer memory layout: repository memory now lives under `docs/maintainer/`, while version-specific execution briefs are treated as external working documents instead of tracked repo artifacts.

## v5.05
- Added Quest real-frame source abstraction (`IByesFrameSource`) and PCA-ready capture path scaffolding (`ByesPcaFrameSource`) with render-texture fallback, plus frame-source metadata in `/api/frame` uploads.
- Added Desktop Console runtime UI (`GET /ui`, `GET /api/ui/state`) to expose real/mock evidence, provider status, latest frame/overlay previews, and one-click actions (assist/mode/record/ping).
- Extended Gateway overlay bus so DET/SEG/DEPTH generate `vis.overlay.v1` companion events and latest overlay asset tracking for Quest HUD + desktop preview.
- Extended Quest smoke panel observability: provider summary (`real/mock/off`), capture source/resolution, and capability refresh integrated into low-overhead probe loop.
- Added one-command launcher `tools/quest3/quest3_usb_realstack_v5_05.cmd` (USB reverse + gateway/inference + optional pySLAM bridge + desktop console open).

## v5.04
- Added Quest vision-HUD pipeline for real-time overlays: `det.objects.v1` boxes + labels/track id, `seg.mask.v1` assets, and `depth.map.v1` assets (binary payloads served via `/api/assets/{asset_id}`).
- Added Gateway asset endpoints and cache metadata endpoint: `GET /api/assets/{asset_id}` and `GET /api/assets/{asset_id}/meta` for HUD texture transport without base64 inflation in WS events.
- Added optional ASR ingress endpoint `POST /api/asr` with mock default backend and optional faster-whisper backend, plus `asr.transcript.v1` event emission.
- Extended Quest recording manager to persist referenced visual assets into run package `assets/` and keep replay/report pipeline compatibility.
- Added Quest v5.04 one-click USB launcher `tools/quest3/quest3_usb_realstack_v5_04.cmd` (gateway + inference + optional pySLAM bridge detection) and updated runbook evidence checklist.
- Refactored Quest wrist menu IA to `Home / Vision / Guidance / Voice / Dev`, with pin-to-home favorites, voice test controls, and explicit panel move/resize gating.
- Added passthrough extended controls (`on/off`, `opacity`, `color/gray` when supported), plus v5.04 self-test extensions for HUD assets, TTS/ASR checks, and optional pySLAM realtime status.

## v5.03
- Added target-tracking assist flow on top of frame cache: `POST /api/assist` now supports `target_start / target_step / target_stop` with device-scoped session TTL and emits `target.session` / `target.update` events.
- Added optional Quest guidance output stack (text + spatial audio + haptics toggles) and wired target updates into panel telemetry (`Last TARGET` + age).
- Added optional passthrough controller bridge (`ByesPassthroughController`) and menu-controlled toggle path with runtime status feedback.
- Added optional pySLAM runner script `Gateway/scripts/pyslam_run_package.py` and lightweight optional `services/pyslam_service` bridge scaffold.
- Added v5.03 one-click USB launcher `tools/quest3/quest3_usb_realstack_v5_03.cmd` for adb reverse + gateway/inference startup with find/assist/record defaults.

## v5.02
- Added promptable `Find` path on top of real DET stack: Gateway now supports `find` via DET prompt overrides and Quest hand menu exposes one-tap find presets (`door`, `exit sign`, `stairs`, `elevator`, `restroom`, `person`).
- Added Gateway frame-cache assist endpoint `POST /api/assist` so OCR/DET/FIND/RISK/DEPTH actions can run against the latest cached frame (no mandatory re-upload from Quest when cache is fresh).
- Added Gateway recording endpoints `POST /api/record/start` and `POST /api/record/stop`; recording writes Quest run-package artifacts (`frames`, `frames_meta.jsonl`, `events/events_v1.jsonl`, `manifest.json`) under `runs/quest_recordings/`.
- Quest panel now surfaces `Last FIND` and `Guidance` with age, and adds FIND/autospeak/guidance controls with speech dedupe/cooldown protection.
- Added one-command USB launcher `tools/quest3/quest3_usb_realstack_v5_02.cmd` for adb reverse + gateway + inference real-stack profile and dependency diagnostics.

## v5.01
- Added real OCR provider path in `inference_service` via PaddleOCR (`BYES_SERVICE_OCR_PROVIDER=paddleocr`) with normalized `ocr.read` payloads and dependency-missing 503 diagnostics.
- Added real DET provider path in `inference_service` via Ultralytics YOLO (`BYES_SERVICE_DET_PROVIDER=ultralytics`) and normalized `det.objects` events.
- Extended `/api/frame` inference orchestration with forced target metadata (`meta.targets`) and added Gateway capabilities endpoint `GET /api/capabilities` for runtime panel/self-test diagnostics.
- Added depth-based fused risk event emission (`risk.fused`) from depth grid payload as a lightweight hazard fallback.
- Quest output usability upgrades: panel now shows `Last OCR/DET/RISK + Age(ms)`, supports `Read Text Once`/`Detect Once`, and autospeak toggles with cooldown+dedupe guard.
- Added USB real-stack launcher `tools/quest3/quest3_usb_realstack_v5_01.cmd` for one-command `adb reverse + gateway+inference` startup and dependency hints.

## v5.00
- Switched Quest entry interaction from custom wrist buttons to an official palm-up hand menu flow (XRI `HandMenu` + `MetaSystemGestureDetector`) with multi-page navigation.
- Added grouped menu pages (`Connection / Actions / Mode / Panels / Settings / Debug`) with mode roundtrip controls, panel management, debug copy/export, and passthrough toggle.
- Added safe gesture shortcut model with conflict isolation: shortcuts run only when menu is hidden, no grab/UI conflict is active, and system gesture is not active.
- Added explicit smoke panel move/resize mode gate (default OFF), lock-to-head toggle, and reset pose/scale operations to avoid accidental panel drag while pinching UI.
- Added runtime guide disabler to suppress MR Template coaching/guide menu objects in `Quest3SmokeScene` by default.
- Updated scene installer to wire `BYES_HandMenuRoot`, `ByesMrTemplateGuideDisabler`, and enforce `Quest3SmokeScene` as the only build scene by default.

## v4.99
- Quest3 smoke UX upgraded to a wrist/palm menu flow: grouped actions (`Actions / Panels / Debug`) and no dependency on bottom button controls for Quest operation.
- Added XR Hands gesture shortcuts on right hand: thumb+index pinch (`Scan Once`), thumb+middle (`Live Toggle`), thumb+ring (`Cycle Mode`) with cooldown/hysteresis and safe no-op fallback when hand subsystem is unavailable.
- Smoke panel now supports runtime move/adjust operations (grab shell, pin/unpin, distance/scale, snap-to-default) wired to Quest menu actions.
- Quest smoke installer now auto-injects wrist menu + gesture components and disables coaching/tutorial UI by default in `Quest3SmokeScene`.
- Added editor auto-open helper for Quest smoke scene (`BYES/Quest3/Auto Open Quest3SmokeScene`) and updated Quest runbook for the new no-controller workflow.

## v4.98
- Quest3 hitch mitigation: capture path now supports async GPU readback with Android-friendly defaults and sync fallback when unsupported/failing.
- Added Quest runtime hitch telemetry (`Hitch30s`, `WorstDt`, `AvgDt`, `GC delta`) and surfaced capture runtime state (`CaptureHz`, inflight, async on/off) in the floating panel.
- Quest panel mode controls now actively switch mode (`Walk/Read/Inspect`) via `POST /api/mode` and verify with `GET /api/mode`.
- Reduced periodic runtime churn in smoke UX: reachability polling throttled to low frequency plus explicit `Refresh` button for manual checks.

## v4.97
- Quest3 smoke loop now includes one-tap frame upload and live toggle in the minimal world-space panel (`Scan Once` / `Live Start-Stop`), with panel-side status for HTTP, WS, last upload cost, coarse E2E, and last event type.
- Quest3 self-test runner was aligned to the practical smoke chain: `ping -> version -> mode -> scan once + ws event` with explicit PASS/FAIL reasons shown in-panel.
- Quest3 smoke installer now auto-populates `BYES_FrameRig` in `Quest3SmokeScene` and wires `GatewayClient + ScreenFrameGrabber + FrameCapture + GatewayFrameUploader + ScanController` using Quest-friendly defaults.
- USB smoke launcher now enables WS v1/net debug emission for smoke verification (`BYES_INFERENCE_EMIT_WS_V1=1`, `BYES_EMIT_NET_DEBUG=1`) so Quest can reliably observe WS feedback after scans.

## v4.96.1
- Quest3 UI clickability fix: prevent runtime mode overlay from intercepting interactions (Android suppress + non-blocking overlay graphics/raycast settings).
- Enforced world-space Quest connection panel raycast path: bind camera, raise sorting order, prefer `TrackedDeviceGraphicRaycaster`, and keep panel root interactable.
- Added runtime XR UI wiring guard (`ByesXrUiWiringGuard`) to normalize EventSystem modules (`XRUIInputModule`) and enable UI interaction on `XRRayInteractor` instances.
- Updated Quest3 smoke scene installer to auto-place `BYES_XrUiWiringGuard` under `BYES_SmokeRig`.

## v4.96
- Added Quest 3 smoke scene auto-installer that ensures `BYES_SmokeRig/BYES_ConnectionPanel` exists in `Quest3SmokeScene`.
- Added runtime head-locked world-space panel behavior (`ByesHeadLockedPanel`) to keep panel stable in front of the user.
- Added a prefab-free minimal connection panel (`ByesQuest3ConnectionPanelMinimal`) with Ping / Version / Mode probes and periodic HTTP reachability checks.
- Added batch entrypoint `BYES.Editor.ByesQuest3SmokeSceneInstaller.InstallFromBatch` for no-click scene installation.
- Updated Quest runbook with troubleshooting when users only see MODE text but no connection panel.

## v4.95
- Added Quest3 Android batch build entrypoint `BYES.Editor.ByesBuildQuest3.BuildQuest3SmokeApk` and output pipeline to `Builds/Quest3/`.
- Added one-command local Android build runner `tools/unity/build_quest3_android.cmd` and companion build guide `tools/unity/README_BUILD_ANDROID.md`.
- Added Unity build log root-cause parser `tools/unity/parse_unity_build_log.py` that extracts earliest true errors with context.
- Added USB-first Quest3 gateway launcher `tools/quest3/quest3_usb_local_gateway.cmd` (adb reverse + local gateway on port 18000).
- Updated Quest3 runbook with USB recommended path, WinError 10013 mitigation, and smoke checklist.

## v4.94
- Quest3 zero-controller smoke loop: added startup self-test runner (`ping`, `version`, `mode`, short live-loop metrics) with PASS/FAIL summary in runtime panel.
- Input System migration hardening: removed unguarded legacy `Input.GetKey*` calls from BYES runtime scripts and kept legacy API behind `#if ENABLE_LEGACY_INPUT_MANAGER`.
- Suppressed XR hand-tracking spam in `Quest3SmokeScene` by auto-disabling `XRInputModalityManager` when no running `XRHandSubsystem` exists.
- Added Windows one-command smoke launcher `tools/quest3/quest3_smoke.ps1` (USB/LAN) for Gateway boot + optional adb reverse setup.
- Added CI guard `tools/check_unity_legacy_input.py` and workflow step to prevent legacy-input regressions.

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
