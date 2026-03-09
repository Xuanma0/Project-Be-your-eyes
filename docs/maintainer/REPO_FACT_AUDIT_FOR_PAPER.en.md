# REPO_FACT_AUDIT_FOR_PAPER

## 0. One-Page Conclusion
- This repository is not a single demo. It is a mixed monorepo containing a Unity/Quest frontend, a Python Gateway backend, standalone inference/planner/SLAM reference services, and a substantial run-package evaluation and replay toolchain.
- Based on code evidence, the most accurate current characterization is a runnable prototype with strong engineering-oriented evaluation infrastructure, not a fully converged product system and not an algorithm-centric paper codebase.
- The safest main system entrypoints are Unity's `Assets/Scenes/Quest3SmokeScene.unity` and Python's `Gateway/main.py`. The former is the only enabled build scene; the latter aggregates `/api/frame`, `/ws/events`, `/api/assist`, `/api/plan`, recording, and asset-serving endpoints.
- The Quest-side main loop is genuinely implemented as `capture -> upload -> backend inference/event generation -> websocket/asset return -> HUD/TTS/haptics/ack`.
- The backend already implements provider abstraction, mode switching, caching, recording, reporting, replay, regression tests, and contract tests. This is the strongest and most paper-ready part of the repository.
- Relative to the intended paper narrative, the codebase is clearly transitional: Unity still contains an older `BeYourEyes.*` event-bus line and a newer `BYES.*` Quest smoke line; the backend still contains both an older scheduler/tool-registry/fusion line and a newer inference-v1 line.
- OCR, detection, risk sensing, depth, segmentation, SLAM pose, recording, and reporting all have code evidence. However, not every module is clearly in the default current Quest smoke main path.
- “Open-vocabulary detection” can only be written conservatively as a prompt-conditioned detection path. The code does pass `prompt` and `targets`, and `UltralyticsDetProvider` does try `set_classes`, but this is not enough to claim a mature open-vocabulary method contribution.
- “Active perception,” “hand-eye coordination,” “VLM/VLA control,” and a complete user-facing 3D mapping/SLAM loop cannot be honestly written as stable mainline capabilities today. Some appear only as backend context/adapters/services; others only as UI or offline evaluation hooks.
- Planning and LLM-related code is not absent. `/api/plan`, `planner_service`, `RealVlmTool`, and Unity `PlanClient`/`ActionPlanExecutor` do exist. But the current Quest smoke scene does not clearly place `PlanClient`/`PlanExecutor`/`ActionPlanExecutor` on the main path, so LLM/VLM planning cannot be claimed as the default user workflow.
- Low-latency-oriented system design is real in code: fast/slow queues, TTL, cancel-older-frame behavior, preempt windows, event TTL/reorder guards, local fallbacks, asset/frame caches, and cached assist resubmission are all implemented. But this only supports a low-latency-oriented design claim, not a performance conclusion.
- The safest paper positioning is an assistive AI systems/prototype/engineering-heavy paper, not a pure algorithms paper.
- The most defensible contribution claims are: an end-to-end Quest assistive vision prototype, mode-aware asynchronous scheduling and safety degradation, run-package observability/evaluation infrastructure, and explicit multi-provider capability/truth-state handling.
- The claims that must not be overstated now are: SOTA performance, user benefit, verified real-time performance, validated edge-cloud advantage, mature active perception, mature hand-eye coordination, completed user studies, and systematic robustness validation.

## 1. Repository Basics
- Repository type: mixed monorepo. Unity project, Python Gateway, standalone services, tests, regression suites, and artifact directories coexist.
- Main languages/frameworks: C# + Unity 6000.3.10f1; Python + FastAPI/Flask; some PowerShell/CI scripts.
- Core dependencies:
  - Unity: `Packages/manifest.json:3`, `Packages/manifest.json:4`, `Packages/manifest.json:17`, `Packages/manifest.json:18`, `Packages/manifest.json:20` show `NativeWebSocket`, `com.unity.ai.inference`, `XR Hands`, `XR Interaction Toolkit`, and `Meta OpenXR`.
  - Python: `Gateway/requirements.txt:1`, `Gateway/requirements.txt:2`, `Gateway/requirements.txt:8` show `fastapi`, `uvicorn`, `pytest`, and related tooling.
- Main runtime environment:
  - Enabled build scene: `ProjectSettings/EditorBuildSettings.asset:9`
  - Unity version: `ProjectSettings/ProjectVersion.txt:1`
  - Gateway CI: `.github/workflows/gateway-ci.yml:36`, `.github/workflows/gateway-ci.yml:40`, `.github/workflows/gateway-ci.yml:44`, `.github/workflows/gateway-ci.yml:52`
- Git state:
  - Branch: `feature/unity-skeleton`
  - HEAD: `6472fff`
  - Last commit: `6472fff 2026-03-08 fix(v5.08.2): real bring-up & ux hotfix (provider truth fail-closed + overlay asset cache + passthrough fallback + menu/controller polish)`
  - Dirty worktree: `.gitignore`, `Gateway/main.py`, `tools/quest3/quest3_usb_realstack_v5_08_2.cmd`
- Directory overview:
  - Root: `.github`, `Assets`, `Gateway`, `Packages`, `ProjectSettings`, `docs`, `schemas`, `tools`
  - `Assets/`: `BeYourEyes`, `Scenes`, `Scripts`, `Prefabs`, `XR`
  - `Gateway/`: `main.py`, `byes/`, `services/`, `scripts/`, `tests/`, `regression/`, `artifacts/`
  - `Gateway/services/`: `inference_service`, `planner_service`, `pyslam_service`, `reference_*`, `sam3_seg_service`, `da3_depth_service`
- Maturity assessment: runnable prototype plus unusually strong replay/evaluation/regression infrastructure. It is not “just scaffolding,” but it is also not a fully cleaned-up product-ready stack.

## 2. Main System Entry and Main Path
- Candidate entrypoints:
  - Unity build scene: `Assets/Scenes/Quest3SmokeScene.unity`
  - Unity bootstrap: `Assets/BeYourEyes/AppBootstrap.cs:11`, `Assets/BeYourEyes/AppBootstrap.cs:51`
  - Unity Quest smoke panel: `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`
  - Unity capture/upload controller: `Assets/BeYourEyes/Unity/Interaction/ScanController.cs:15`
  - Unity HTTP/WS client: `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:24`
  - Backend aggregator: `Gateway/main.py:2695`
  - Standalone inference service: `Gateway/services/inference_service/app.py:47`
  - Standalone planner service: `Gateway/services/planner_service/app.py:592`
  - Standalone pySLAM service: `Gateway/services/pyslam_service/app.py:39`
- My judgment of the main entrypoints:
  - Frontend: `Quest3SmokeScene`, because it is the only enabled build scene and contains `ByesQuest3ConnectionPanelMinimal`, `GatewayClient`, `ScanController`, `GatewayWsClient`, and `AppBootstrap`.
  - Backend: `Gateway/main.py`, because it exposes the actual frame ingest, capability, assist, record, plan, confirm, websocket, and asset routes.
- Main call chain:
  1. The Quest scene starts and loads `AppBootstrap` and the smoke components. Evidence: `Quest3SmokeScene.unity:2223`, `Quest3SmokeScene.unity:2508`, `Quest3SmokeScene.unity:2602`.
  2. The user triggers scan/mode/find/record actions through the panel, hand menu, or controllers. Evidence: `ByesHandMenuController.cs:369`, `ByesHandMenuController.cs:373`, `ByesQuest3ConnectionPanelMinimal.cs:1463`, `ByesQuest3ConnectionPanelMinimal.cs:1551`.
  3. `ScanController` captures a JPG from an `IByesFrameSource` and builds frame metadata. Evidence: `ScanController.cs:402`, `ScanController.cs:403`, `ScanController.cs:835`.
  4. The frame is uploaded via `/api/frame`. Evidence: `GatewayClient.cs:657`, `GatewayFrameUploader.cs:56`, `Gateway/main.py:2907`.
  5. Gateway records and caches the frame, submits it to the scheduler, and also runs the inference-v1 path. Evidence: `Gateway/main.py:2175`, `Gateway/main.py:2185`, `Gateway/main.py:3039`, `Gateway/main.py:777`, `Gateway/main.py:789`.
  6. The backend runs OCR, risk, detection, depth, segmentation, and SLAM according to mode and target selection, then emits `byes.event.v1` rows and overlay assets. Evidence: `Gateway/main.py:1553`, `Gateway/main.py:1710`, `Gateway/main.py:1772`, `Gateway/main.py:1900`, `Gateway/main.py:1963`, `Gateway/main.py:2043`, `Gateway/main.py:2088`.
  7. Unity receives `/ws/events` and filters them using TTL/reorder/fallback gates. Evidence: `GatewayClient.cs:848`, `GatewayClient.cs:1002`, `GatewayClient.cs:1051`, `Gateway/main.py:11940`.
  8. The Quest HUD fetches `/api/assets/{asset_id}`, renders overlays, outputs speech/haptics, and sends user-side ack events. Evidence: `ByesVisionHudRenderer.cs:425`, `SpeechOrchestrator.cs:203`, `LocalSafetyFallback.cs:269`, `Gateway/main.py:3075`.
- If multiple versions exist, which one appears current:
  - The `BYES.*` smoke path looks like the current Quest-facing line: `ByesQuest3ConnectionPanelMinimal` + `GatewayClient` + `ScanController` + `ByesVisionHud*` + `ByesHandMenuController`.
  - The older line still exists: `AppBootstrap` + `GatewayWsClient` + `GatewayPoller` + `AppServices` bus. Evidence: `AppBootstrap.cs:78`, `Quest3SmokeScene.unity:2207`.
  - Planning executors exist but are not explicitly present in the Quest smoke scene. `ByesRuntimeBootstrap` only wires them if they exist. Evidence: `ByesRuntimeBootstrap.cs:60`, `ByesRuntimeBootstrap.cs:70`.
  - `ByesWristMenuController` should be treated as legacy UI because `ByesHandMenuController` explicitly disables it. Evidence: `ByesHandMenuController.cs:126`, `ByesHandMenuController.cs:1646`.

## 3. Reconstructed Architecture
- Text summary:
  - The local frontend is a Unity/Quest client handling camera capture, mode switching, hand/controller input, websocket event consumption, HUD/overlay rendering, TTS/haptic output, and local fallback logic.
  - The central backend is `Gateway/main.py`, which receives frames, maintains frame/asset/run-package state, schedules work, calls providers, emits events, and serves plan/record/assist/asset endpoints.
  - The model/service layer includes both in-process provider wrappers and external HTTP services such as `inference_service`, `planner_service`, `sam3_seg_service`, `da3_depth_service`, `reference_slam_service`, and `pyslam_service`.
  - The offline layer is the run-package toolchain for recording, replay, reporting, regression, and benchmarking.
- ASCII diagram:

```text
[Quest / Unity local]
  ByesHandMenuController / ConnectionPanel / ScanController
    -> ByesPcaFrameSource / RenderTexture fallback
    -> GatewayClient or GatewayFrameUploader
    -- HTTP /api/frame, /api/assist, /api/mode, /api/record/* -->

                        [Gateway/main.py]
  /api/frame -> FrameCache + RecordingManager + scheduler.submit_frame
                                  -> _run_inference_for_frame(...)
                                  -> emits byes.event.v1 / assets / ws rows
  /api/assist -> reuse cached frame -> forceTargets/prompt -> resubmit
  /api/plan   -> plan_pipeline -> planner backend/service
  /ws/events  -> Unity
  /api/assets/{id} -> Unity HUD fetch

              [Provider / Service layer]
  OCR: paddleocr / tesseract / http / mock
  DET: ultralytics / yolo26 / mock
  RISK: reference / heuristic / http / mock
  SEG: http SAM3 / mock
  DEPTH: onnx / http / DA3 / mock
  SLAM: mock / http / reference_slam_service / pyslam_service
  PLAN: reference / llm / pov

[Quest feedback local]
  GatewayClient (WS)
    -> EventGuard + LocalActionPlanGate + LocalSafetyFallback
    -> ByesVisionHudRenderer (/api/assets/{id})
    -> SpeechOrchestrator / Haptics / FrameTelemetry ack

[Offline / evaluation]
  RecordingManager -> run package
  report_run.py / run_regression_suite.py / run_dataset_benchmark.py / eval_slam_tum.py
```

- Frontend/backend boundary:
  - Frontend: `Assets/BeYourEyes/*`, `Assets/Scripts/BYES/*`
  - Backend: `Gateway/main.py`, `Gateway/byes/*`
- Communication boundary:
  - HTTP: `/api/frame`, `/api/assist`, `/api/mode`, `/api/asr`, `/api/record/*`, `/api/plan`, `/api/assets/{id}`
  - WebSocket: `/ws/events`
- Sync/async boundary:
  - Unity capture, HTTP requests, asset fetches, and feedback are coroutine/event-driven.
  - Gateway has FAST/SLOW scheduler workers, while the direct inference-v1 path is another asynchronous runtime path.
  - Standalone services are cross-process HTTP dependencies.
- Local/cloud boundary:
  - Confirmed local components: capture, HUD, TTS/haptics, local fallback, event filtering, and hand/controller UI.
  - “Edge/cloud collaboration” is only supportable as an architectural capability today. The repository does not by itself prove a fixed deployment split has been systematically validated.
- Fallback/degrade modes:
  - Client side: `LocalSafetyFallback`, `LocalActionPlanGate`, `EventGuard`
  - Backend side: scheduler TTL/cancel/preempt logic, planner fallback, provider truth/override handling, safe-mode/degraded paths

## 4. Module-Level Fact Audit
### 4.1 Frame Capture and Upload
- Status: Implemented
- Code evidence:
  - Capture controller: `Assets/BeYourEyes/Unity/Interaction/ScanController.cs:15`, `Assets/BeYourEyes/Unity/Interaction/ScanController.cs:402`
  - Main frame source interface: `Assets/Scripts/BYES/Quest/ByesPcaFrameSource.cs:13`
  - PCA/fallback truth states: `ByesPcaFrameSource.cs:15`, `ByesPcaFrameSource.cs:17`, `ByesPcaFrameSource.cs:18`, `ByesPcaFrameSource.cs:739`
  - Upload path: `GatewayClient.cs:301`, `GatewayFrameUploader.cs:17`, `Gateway/main.py:2907`
- Inputs/outputs:
  - Input: Quest camera/PCA frame or fallback frame, plus capture/source-truth metadata.
  - Output: `/api/frame` multipart upload, triggering backend frame cache, recording, and inference.
- Upstream/downstream:
  - Upstream: `ByesHandMenuController`, `ByesQuest3ConnectionPanelMinimal`, live loop/manual triggers.
  - Downstream: Gateway frame ingest, scheduler, recording.
- Current completeness:
  - This is a real main-path feature.
  - Source truth is explicit: `pca_real`, `ar_cpuimage_fallback`, `rendertexture_fallback`, `unavailable`.
- Risks/gaps:
  - Code exists, but this audit did not perform Quest device validation.
  - Real PCA operation still depends on device, permissions, ARFoundation subsystems, and runtime environment.

### 4.2 Detection / Find / Target Tracking
- Status: Partially Implemented
- Code evidence:
  - Quest find/assist entrypoints: `ByesQuest3ConnectionPanelMinimal.cs:1551`, `ByesQuest3ConnectionPanelMinimal.cs:2063`
  - `targets`/`prompt` passed from scan metadata: `ScanController.cs:867`, `ScanController.cs:873`
  - Assist path builds `openVocab` prompt metadata: `Gateway/main.py:4814`, `Gateway/main.py:4824`, `Gateway/main.py:4827`
  - Detection result events: `Gateway/main.py:1710`, `Gateway/main.py:7813`, `Gateway/main.py:7841`
  - Ultralytics prompt label extraction and `set_classes`: `ultralytics_det.py:126`, `ultralytics_det.py:153`, `ultralytics_det.py:175`, `ultralytics_det.py:179`
  - Target session/update: `Gateway/byes/target_tracking/store.py:32`, `Gateway/byes/target_tracking/manager.py:8`, `Gateway/byes/target_tracking/manager.py:78`, `Gateway/main.py:4889`, `Gateway/main.py:4907`
- Inputs/outputs:
  - Input: current or cached frame, `targets=["det"]`, optional `prompt.text`, optional tracking session/ROI.
  - Output: `det.objects.v1`, `target.session`, `target.update`, HUD text and overlays.
- Upstream/downstream:
  - Upstream: hand menu, smoke panel, “find concept”, track start/step/stop.
  - Downstream: `ByesVisionHudRenderer`, panel text state, `ByesGuidanceEngine`.
- Current completeness:
  - Detection plus target-session tracking are real and present in the Quest smoke path.
  - But “open-vocabulary detection” is only evidenced as prompt-conditioned class filtering / target filtering, not as a mature open-vocabulary method.
- Risks/gaps:
  - This must not be written as a YOLO-World/SAM-level method contribution.
  - No paper-ready quantitative evidence was found for open-vocabulary generalization or tracking robustness.

### 4.3 OCR / Text Reading
- Status: Implemented
- Code evidence:
  - OCR trigger: `Gateway/main.py:1581`
  - Inference-service OCR endpoint: `Gateway/services/inference_service/app.py:388`
  - OCR provider factory: `Gateway/services/inference_service/providers/__init__.py:31`
  - PaddleOCR provider: `paddleocr_ocr.py:43`, `paddleocr_ocr.py:56`, `paddleocr_ocr.py:71`
  - Quest read/OCR assist path: `ByesQuest3ConnectionPanelMinimal.cs:2024`
- Inputs/outputs:
  - Input: image frame, optionally targets/prompt.
  - Output: OCR result events, spoken text, report metrics.
- Upstream/downstream:
  - Upstream: `read_text` mode, assist, hand menu.
  - Downstream: `SpeechOrchestrator`, report/benchmark pipeline.
- Current completeness:
  - OCR is one of the most solid modules in the repository.
- Risks/gaps:
  - “Screen content understanding” beyond OCR itself was not supported by repo evidence.
  - Real OCR quality still depends on installed optional dependencies and weights; not validated in this audit.

### 4.4 Risk / Hazard Sensing
- Status: Implemented
- Code evidence:
  - Risk trigger: `Gateway/main.py:1628`
  - FAST-lane critical preemption: `Gateway/byes/scheduler.py:239`, `Gateway/byes/scheduler.py:852`, `Gateway/byes/scheduler.py:906`
  - SafetyKernel guardrails: `Gateway/byes/safety_kernel.py:24`
  - Quest-side risk speech: `SpeechOrchestrator.cs:229`, `SpeechOrchestrator.cs:247`
  - Local fallback state machine: `LocalSafetyFallback.cs:8`, `LocalSafetyFallback.cs:94`
- Inputs/outputs:
  - Input: frames, risk backend outputs, health/degradation state.
  - Output: `risk.*` events, critical stop/confirm guardrails, TTS/haptics, safety UI state.
- Upstream/downstream:
  - Upstream: frame ingest, scheduler, direct inference.
  - Downstream: speech/HUD/local gates/planning.
- Current completeness:
  - Hazard sensing plus safety feedback/blocking are real main-path capabilities.
- Risks/gaps:
  - The code does not by itself justify a claim of validated safety effectiveness.

### 4.5 Occupancy / Costmap
- Status: Partially Implemented
- Code evidence:
  - `CostmapFuser`: `Gateway/byes/mapping/costmap_fuser.py:36`
  - Costmap event emission: `Gateway/main.py:2043`, `Gateway/main.py:2088`, `Gateway/main.py:2130`
  - Report/benchmark metrics: `run_dataset_benchmark.py:73`, `run_dataset_benchmark.py:78`
- Inputs/outputs:
  - Input: depth/seg/slam payloads, optional dynamic masks/tracks.
  - Output: `map.costmap`, `map.costmap_fused`, `map.costmap_context`.
- Upstream/downstream:
  - Upstream: depth, segmentation, SLAM.
  - Downstream: planner context, reports, benchmarks.
- Current completeness:
  - The backend algorithm and the evaluation-side metrics are clearly implemented.
  - A clear Quest user-facing costmap consumer was not found on the current smoke main path.
- Risks/gaps:
  - Safe wording: backend costmap/fused-costmap support exists.
  - Unsafe wording: user-facing occupancy navigation loop is complete.

### 4.6 Depth Estimation
- Status: Implemented
- Code evidence:
  - Backend depth trigger and depth map events: `Gateway/main.py:1726`, `Gateway/main.py:1772`, `Gateway/main.py:7956`
  - Inference-service depth endpoint: `Gateway/services/inference_service/app.py:715`
  - Local ONNX depth provider: `onnx_depth.py:94`
  - External DA3 depth service: `da3_depth_service/app.py:26`, `da3_depth_service/app.py:247`
  - Quest HUD depth overlay: `ByesVisionHudRenderer.cs:213`
- Inputs/outputs:
  - Input: image frame.
  - Output: `depth.map.v1`, depth metrics, optional risk fusion.
- Upstream/downstream:
  - Upstream: frame ingest.
  - Downstream: risk fusion, HUD overlay, costmap.
- Current completeness:
  - Depth exists across backend runtime, standalone services, tests, and reports.
- Risks/gaps:
  - “Real-time accurate depth” still requires experiments.
  - The DA3 path is an external service path, not a native repo-internal algorithm contribution.

### 4.7 3D Mapping / SLAM
- Status: Partially Implemented
- Code evidence:
  - Gateway direct SLAM path and events: `Gateway/main.py:1920`, `Gateway/main.py:1963`, `Gateway/main.py:8007`
  - Inference-service SLAM endpoint: `Gateway/services/inference_service/app.py:791`
  - Reference SLAM service: `reference_slam_service/app.py:28`, `reference_slam_service/app.py:224`
  - pySLAM proxy service: `pyslam_service/app.py:39`, `pyslam_service/app.py:55`
  - TUM evaluation scripts: `Gateway/scripts/eval_slam_tum.py`, `Gateway/scripts/run_pyslam_on_run_package.py`
- Inputs/outputs:
  - Input: image frame, optional pose/targets/prompt metadata.
  - Output: `slam.pose.v1`, `slam.trajectory.v1`, TUM-style trajectory metrics.
- Upstream/downstream:
  - Upstream: frame ingest, optional external SLAM service.
  - Downstream: costmap, planner context, reports.
- Current completeness:
  - “SLAM pose interface + reference/proxy service + evaluation tooling” is clearly real.
  - A mature native SLAM core inside this repository was not found; the dominant pattern is mock/http/reference/pyslam-proxy integration.
- Risks/gaps:
  - It is not honest to describe the current repo as a complete user-facing 3D mapping system.
  - Safe wording: SLAM pose/trajectory integration and evaluation hooks.

### 4.8 Hand Input / Hand-Eye Coordination
- Status: Partially Implemented
- Code evidence:
  - XR hand subsystem guard: `ByesXrSubsystemGuards.cs:36`
  - Wrist anchor and palm-up menu: `ByesWristMenuAnchor.cs:82`, `ByesWristMenuAnchor.cs:115`
  - Hand gesture shortcuts: `ByesHandGestureShortcuts.cs:116`, `ByesHandGestureShortcuts.cs:233`
  - New hand menu controller: `ByesHandMenuController.cs:188`
- Inputs/outputs:
  - Input: XR hand joints, palm orientation, pinch/gesture/controller buttons.
  - Output: menu activation, mode switches, find/read/record UI commands.
- Upstream/downstream:
  - Upstream: XR Hands / XR input subsystem.
  - Downstream: method calls into `ByesQuest3ConnectionPanelMinimal`.
- Current completeness:
  - Hand-based UI interaction is real.
  - An assistive hand-eye coordination control loop was not supported by repository evidence.
- Risks/gaps:
  - This must not be presented as a hand-eye coordination research contribution.

### 4.9 Active Perception / POV / View Planning
- Status: Partially Implemented
- Code evidence:
  - POV context API: `Gateway/main.py:5407`
  - Plan pipeline reads POV/seg/slam/costmap context: `Gateway/byes/plan_pipeline.py:10`, `Gateway/byes/plan_pipeline.py:109`
  - Planner `pov` provider and adapter: `planner_service/app.py:621`, `pov_adapter.py:36`
- Inputs/outputs:
  - Input: POV IR from run packages, context budget, planner request.
  - Output: POV context packs and action plans derived from POV IR.
- Upstream/downstream:
  - Upstream: run packages / POV IR.
  - Downstream: `/api/plan`, report metrics.
- Current completeness:
  - POV/active-context handling exists on the backend and evaluation/planning side.
  - A live camera-control/view-planning closed loop was not found on the current main runtime path.
- Risks/gaps:
  - Do not write this as an online active-perception capability.
  - Safer wording: “POV-derived context and planning hooks.”

### 4.10 Planning / Agent / VLM / VLA
- Status: Partially Implemented
- Code evidence:
  - Gateway `/api/plan`: `Gateway/main.py:5599`
  - Plan pipeline: `Gateway/byes/plan_pipeline.py:251`
  - Planner service `reference`/`llm`/`pov`: `planner_service/app.py:377`, `planner_service/app.py:495`, `planner_service/app.py:592`, `planner_service/app.py:577`, `planner_service/app.py:579`
  - Unity plan client/executors: `PlanClient.cs:11`, `PlanClient.cs:95`, `ActionPlanExecutor.cs:8`, `PlanExecutor.cs:9`
  - Legacy slow-lane `RealVlmTool`: `real_vlm.py:12`, `Gateway/main.py:934`
- Inputs/outputs:
  - Input: POV/seg/slam/costmap context, risk summary, constraints, optional LLM endpoint.
  - Output: `byes.action_plan.v1`, confirm/action events, report rows.
- Upstream/downstream:
  - Upstream: run-package context or current Gateway state.
  - Downstream: `ActionPlanExecutor`, confirm UI, safety kernel.
- Current completeness:
  - The planning backend is real code, not just documentation.
  - But the current Quest smoke scene does not clearly place `PlanClient`/`PlanExecutor`/`ActionPlanExecutor` on its main path; therefore “LLM/VLM-driven main workflow” would be an overclaim.
- Risks/gaps:
  - `llm` depends on an external API/endpoint.
  - `RealVlmTool` also depends on an external URL.
  - No evidence was found for true VLA control.

### 4.11 Unity UI / HUD / Mode Switching / Feedback
- Status: Implemented
- Code evidence:
  - Quest smoke panel: `Quest3SmokeScene.unity:2508`
  - Mode manager: `ByesModeManager.cs:8`
  - Hand menu: `ByesHandMenuController.cs:20`
  - HUD overlay: `ByesVisionHudRenderer.cs:167`, `ByesVisionHudRenderer.cs:425`
  - Passthrough control: `ByesPassthroughController.cs:7`, `ByesPassthroughController.cs:40`
  - Guidance engine: `ByesGuidanceEngine.cs:31`
- Inputs/outputs:
  - Input: gateway events, target updates, mode state, hand/controller input.
  - Output: UI text, overlays, passthrough state, simple guidance, toasts.
- Upstream/downstream:
  - Upstream: `GatewayClient`, hand menu, Quest scene.
  - Downstream: TTS/haptics/ack.
- Current completeness:
  - The Quest-side UI/HUD/mode layer is real code, not a mockup.
  - Guidance is a simple heuristic directional cue, not a full navigation planner.
- Risks/gaps:
  - No user-study evidence was found.
  - Passthrough still depends on Quest hardware, ARFoundation, and permissions.

### 4.12 Voice I/O
- Status: Partially Implemented
- Code evidence:
  - TTS orchestration: `SpeechOrchestrator.cs:10`
  - Backend ASR endpoint: `Gateway/main.py:4662`
  - Quest panel ASR call: `ByesQuest3ConnectionPanelMinimal.cs:3725`
- Inputs/outputs:
  - Input: gateway risk/action/confirm/dialog events or uploaded audio.
  - Output: TTS speech and ASR text responses.
- Upstream/downstream:
  - Upstream: gateway event stream / microphone audio.
  - Downstream: voice interaction loop.
- Current completeness:
  - TTS output is clearly real.
  - ASR has an API path, but a complete voice-agent loop still depends on external resources.
- Risks/gaps:
  - This must not be written as a validated full voice assistant loop.

### 4.13 Logging / Monitoring / Observability / Recording
- Status: Implemented
- Code evidence:
  - Recording manager: `Gateway/byes/recording/manager.py:61`, `Gateway/byes/recording/manager.py:80`, `Gateway/byes/recording/manager.py:189`, `Gateway/byes/recording/manager.py:223`
  - `/api/record/start` and `/api/record/stop`: `Gateway/main.py:4929`, `Gateway/main.py:4953`
  - Reporting/regression/benchmark: `report_run.py:922`, `run_regression_suite.py`, `run_dataset_benchmark.py:1074`
  - CI contract/regression coverage: `.github/workflows/gateway-ci.yml:36`, `.github/workflows/gateway-ci.yml:44`, `.github/workflows/gateway-ci.yml:52`
- Inputs/outputs:
  - Input: frames, events, assets, metrics, ground truth.
  - Output: run packages, reports, benchmark CSV/JSON/MD, regression outcomes.
- Upstream/downstream:
  - Upstream: Gateway runtime and Unity-side ack/record triggers.
  - Downstream: experimental analysis and auditing.
- Current completeness:
  - This is one of the most mature parts of the repository.
- Risks/gaps:
  - Existing run packages and reports show the tooling has been exercised, but they are not automatically paper-ready results.

### 4.14 Safety / Refusal / Privacy Policy
- Status: Partially Implemented
- Code evidence:
  - Local fallback: `LocalSafetyFallback.cs:8`
  - Local action-plan gate: `LocalActionPlanGate.cs:7`
  - Planner safety kernel: `Gateway/byes/safety_kernel.py:24`
  - API-key guard: `Gateway/main.py:2715`, `Gateway/main.py:2822`, `test_gateway_api_key_http.py:18`
  - Dev-endpoint hardening: `test_gateway_dev_endpoints_toggle.py:29`
- Inputs/outputs:
  - Input: risk level, health status, confirm state, HTTP headers/env toggles.
  - Output: stop/confirm guardrails, fallback speech/haptics, 401/403/404 API responses.
- Upstream/downstream:
  - Upstream: risk/planner and gateway config.
  - Downstream: Unity-side feedback and API access control.
- Current completeness:
  - Runtime safety guardrails and API guards are real.
  - A full privacy policy stack, redaction pipeline, or compliance framework was not supported by repository evidence.
- Risks/gaps:
  - The paper must not describe this as a complete privacy/security framework.

## 5. Evidence Table for Algorithms / Models / Services
| Name | Type | Evidence in repo | In main path? | Current role | Notes |
| --- | --- | --- | --- | --- | --- |
| `Gateway Scheduler` | classical systems logic | `Gateway/byes/scheduler.py`, FAST/SLOW queue, TTL, preempt | Yes | backend async scheduling | coexists with direct inference-v1 |
| `FrameCache` | system cache | `Gateway/main.py:777`, `Gateway/byes/frame_cache.py:28` | Yes | assist resubmission | reused by `/api/assist` |
| `AssetCache` | system cache | `Gateway/main.py:781`, `Gateway/byes/asset_cache.py:31` | Yes | overlay asset cache | Quest HUD fetches assets |
| `PaddleOCR` provider | local model | `paddleocr_ocr.py:56`, `paddleocr_ocr.py:71` | Optional | OCR backend | requires optional deps |
| `Ultralytics / YOLO26` provider | local model | `ultralytics_det.py:110`, `yolo26_det.py:7` | Optional | detection backend | not a repo-native detection method contribution |
| prompt-conditioned DET filtering | wrapper logic | `ultralytics_det.py:126`, `ultralytics_det.py:153` | Yes | find-concept path | only safe as conservative wording |
| `reference / heuristic risk` | classical logic | `reference_risk.py`, `heuristic_risk.py` | Optional | hazard scoring | provider chosen by config |
| `HttpSegProvider` | external API wrapper | `http_seg.py:17` | Optional | segmentation proxy | calls external `/seg` |
| `sam3_seg_service` | standalone service | `sam3_seg_service/app.py:26`, `sam3_seg_service/app.py:316` | Optional | external segmentation service | not native inside Gateway |
| `onnx_depth` | local model | `onnx_depth.py:94` | Optional | depth backend | depends on `onnxruntime` |
| `da3_depth_service` | standalone service | `da3_depth_service/app.py:26`, `da3_depth_service/app.py:247` | Optional | external depth service | HTTP-integrated |
| `MockSlamProvider` / `HttpSlamProvider` | mock / external API wrapper | `mock_slam.py:8`, `http_slam.py:17` | Optional | SLAM pose interface | can emit `slam.pose.v1` |
| `reference_slam_service` | standalone service | `reference_slam_service/app.py:28`, `reference_slam_service/app.py:224` | Optional | reference SLAM service | not full user-facing mapping evidence |
| `pyslam_service` | standalone proxy | `pyslam_service/app.py:39`, `pyslam_service/app.py:55` | Optional | pySLAM bridge | mainly offline/service integration |
| `CostmapFuser` | classical algorithm | `Gateway/byes/mapping/costmap_fuser.py:36` | Optional | costmap fusion | backend strong, UI weak |
| `planner_service reference` | classical planner | `planner_service/app.py:377` | Optional | reference/action planning | real `/api/plan` backend path |
| `planner_service llm` | external API wrapper | `planner_service/app.py:495`, `planner_service/app.py:515` | Optional | LLM planning | external dependency |
| `planner_service pov` | adapter | `planner_service/app.py:621`, `pov_adapter.py:36` | Optional | POV IR -> action plan | compiler-like adapter |
| `RealVlmTool` | external API wrapper | `real_vlm.py:12`, `Gateway/main.py:934` | Legacy/Optional | old scheduler slow-lane VLM | unclear on current smoke path |

## 6. Data Flow, Control Flow, and Timing
- How one frame/request flows:
  1. The user triggers `scan/read/find/track` on Quest. Evidence: `ByesHandMenuController.cs:369`, `ByesQuest3ConnectionPanelMinimal.cs:2063`.
  2. `ScanController` captures from `IByesFrameSource` and attaches `capture` and `frameSource` metadata. Evidence: `ScanController.cs:402`, `ScanController.cs:403`, `ScanController.cs:405`.
  3. The frame is posted to `/api/frame`. Evidence: `GatewayClient.cs:657`, `Gateway/main.py:2907`.
  4. Gateway emits `frame.input`, stores the frame in `FrameCache`, and optionally records it. Evidence: `Gateway/main.py:3039`, `Gateway/byes/recording/manager.py:189`.
  5. Gateway submits the frame to the scheduler and also invokes `_run_inference_for_frame`. Evidence: `Gateway/main.py:2175`, `Gateway/main.py:2185`.
  6. Per-frame mode/target gating decides whether OCR/RISK/DET/DEPTH/SEG/SLAM will run. Evidence: `Gateway/byes/scheduler.py:1081`, `Gateway/main.py:1570`, `Gateway/main.py:2006`.
  7. Results are emitted as `byes.event.v1` rows and may create overlay assets. Evidence: `Gateway/main.py:1334`, `Gateway/main.py:1710`, `Gateway/main.py:1772`, `Gateway/main.py:1900`, `Gateway/main.py:1963`.
  8. Quest `GatewayClient` receives `/ws/events` and runs `LocalActionPlanGate` and `EventGuard`. Evidence: `GatewayClient.cs:1002`, `GatewayClient.cs:1051`.
  9. The HUD fetches `/api/assets/{asset_id}` and renders `seg.mask.v1`, `depth.map.v1`, `det.objects.v1`, and `target.update`. Evidence: `ByesVisionHudRenderer.cs:187`, `ByesVisionHudRenderer.cs:425`.
  10. Speech/haptic feedback is emitted and `/api/frame/ack` records user-side e2e timing. Evidence: `SpeechOrchestrator.cs:166`, `Gateway/main.py:3075`.
- What is asynchronous:
  - Unity coroutines for capture/upload/asset fetch/ASR/record/assist.
  - Backend FAST/SLOW scheduler workers.
  - WebSocket event transport on both the new and old client lines.
  - Cross-process HTTP inference/planner service calls.
- Likely latency bottlenecks:
  - Quest-side GPU readback or PCA fallback capture.
  - `/api/frame` upload and JPEG handling.
  - External OCR/SEG/DEPTH/SLAM/LLM HTTP services.
  - Secondary overlay asset fetches via `/api/assets/{id}`.
  - LLM planning or `RealVlmTool`.
- Where caching/degradation/retry exist:
  - `FrameCache` and `AssetCache`
  - `/api/assist` cached-frame resubmission
  - `EventGuard` TTL/reorder filtering
  - `LocalSafetyFallback` with `OK/STALE/DISCONNECTED/SAFE_MODE_REMOTE`
  - `LocalActionPlanGate` block/patch logic
  - Scheduler TTL drop, cancel-older-frame behavior, preempt window, slow-queue drop
  - `planner_service` fallback flags
  - WebSocket reconnect/health probing in `GatewayClient` and `GatewayWsClient`
- Important nuance:
  - The old scheduler/tool-registry path and the new direct inference-v1 path coexist in the current repo.

## 7. Experiments and Reproducibility Audit
- Training scripts:
  - During this audit, a filename-level search over `Gateway` and `Assets` for `train|trainer|training|checkpoint|checkpoints|fit|epoch` found no explicit training entrypoint or checkpoint-management directory.
  - Conclusion: training code was not supported by repo evidence.
- Inference scripts:
  - Present. `Gateway/main.py`, `services/inference_service/app.py`, `services/planner_service/app.py`, and `services/pyslam_service/app.py` are runnable entrypoints.
- Benchmark scripts:
  - Present. Evidence: `run_dataset_benchmark.py:1074`, `eval_slam_tum.py`, `bench_risk_latency.py`.
- Latency / user study / ablation:
  - Latency: scripts and report extraction exist. Evidence: `bench_risk_latency.py`, `report_run.py:1107`.
  - Ablation: scripts exist. Evidence: `ablate_planner.py`, `sweep_depth_input_size.py`, `sweep_seg_prompt_budget.py`, `sweep_plan_context_pack.py`.
  - User study: no repo evidence found.
- Can the full system run end-to-end?
  - At the code level, yes, the necessary entrypoints and run-package recording path exist.
  - In this audit, heavy dependencies were not installed, no Quest device run was performed, and no external model services were started. So the honest statement is: code exists, but runnability was not verified here.
- Fixed test/fixture evidence:
  - `Gateway/tests/fixtures/` contains many minimal run packages, including OCR, segmentation, depth, SLAM, SAM3, DA3, plan, POV, and costmap cases.
  - `Gateway/artifacts/run_packages/` contains many historical run-package artifacts, indicating that the tooling has been exercised.
- CI and regression:
  - Pytest, run-package linting, baseline/contract regression, and contracts-lock verification are all in CI. Evidence: `.github/workflows/gateway-ci.yml:36`, `.github/workflows/gateway-ci.yml:40`, `.github/workflows/gateway-ci.yml:44`, `.github/workflows/gateway-ci.yml:52`.
- Reproducibility judgment: Medium
- Why:
  - Better than low reproducibility because interfaces, fixtures, reports, contract checks, regression suites, and standalone service entrypoints are all in-repo.
  - Worse than high reproducibility because Quest hardware, model weights, external HTTP/API services, optional dependencies, and deployment topology are not fully encapsulated in-repo.

## 8. Code Reality vs Design Goals
| Design goal | Repo evidence | Current conclusion | Paper-writing guidance |
| --- | --- | --- | --- |
| MR/Unity frontend | `Quest3SmokeScene`, `ByesQuest3ConnectionPanelMinimal`, `ScanController`, `GatewayClient` | real frontend prototype exists | write directly |
| WebSocket + HTTP communication | `Gateway/main.py:2907`, `Gateway/main.py:11940`, `GatewayClient.cs:657` | implemented | write directly |
| Edge/cloud collaboration | multiple HTTP providers/services + Quest local fallback + Gateway orchestration | architectural support exists | write carefully |
| Low-latency async pipeline | FAST/SLOW scheduler, TTL, preempt, EventGuard, LocalSafetyFallback | real design and implementation | write carefully |
| Real-time low-latency effect | only instrumentation/report scripts, no formal results cited yet | [results still needed] | do not write as a result claim |
| OCR / text reading | OCR providers + Quest read flow | implemented | write directly |
| Open-vocabulary detection | prompt-conditioned DET + `set_classes` attempt | only partially implemented | write carefully |
| Segmentation / SAM-like path | `HttpSegProvider` + `sam3_seg_service` + `seg.mask.v1` | partially implemented | write carefully |
| Risk / hazard sensing | risk backend + safety fallback + critical guardrails | implemented | write directly |
| Occupancy / costmap | `CostmapFuser` + report metrics | partially implemented | write carefully |
| Depth estimation | onnx/http/DA3 depth + depth map events | implemented | write directly |
| 3D mapping / SLAM | SLAM pose interface, reference/pyslam services, TUM evaluation | partially implemented | write carefully |
| Hand-eye coordination | only hand-input UI/gesture code exists | design goal not realized on assistive main path | do not write |
| Active perception | POV context + planner adapter | partially implemented on backend/planning side | write carefully |
| VLM/VLA control | planner llm provider + `RealVlmTool` adapter | code exists, but not on Quest smoke main path | do not make a strong claim |
| Voice/visual/audio feedback loop | TTS + HUD + ASR endpoint + ack telemetry | partially implemented | write carefully |
| Observability / recording / replay / reports | run-package / report / regression / benchmark | implemented | write directly |
| Safety / degradation / refusal | local gates + safety kernel + API guards | runtime-layer implementation exists | write as runtime safety guardrails, not as a full safety framework |

## 9. Contribution Claims That Are Safe Today
- Claim 1: The repository implements an end-to-end Quest/Unity to Python Gateway assistive-vision prototype covering image capture, backend event generation, HUD/speech/haptic feedback, and user-side ack.
  - Evidence: `ScanController.cs`, `GatewayClient.cs`, `Gateway/main.py:2907`, `Gateway/main.py:11940`, `ByesVisionHudRenderer.cs`, `SpeechOrchestrator.cs`
  - Safety level: High
  - Suggested wording: “We implement an end-to-end Quest-to-Gateway assistive vision prototype with visual, speech, and haptic feedback hooks.”
- Claim 2: The system includes mode-aware asynchronous scheduling and runtime safety degradation, including FAST/SLOW lanes, TTL handling, preemption, local fallback, and action-plan gating.
  - Evidence: `Gateway/byes/scheduler.py`, `Gateway/byes/safety_kernel.py`, `EventGuard.cs`, `LocalSafetyFallback.cs`, `LocalActionPlanGate.cs`
  - Safety level: High
  - Suggested wording: “The prototype includes mode-aware asynchronous scheduling and runtime safety fallbacks on both the backend and the client.”
- Claim 3: The repository includes a run-package-centric recording, replay, reporting, regression, and contract-testing workflow covering perception, planning, latency, and schema consistency.
  - Evidence: `Gateway/byes/recording/manager.py`, `Gateway/scripts/report_run.py`, `Gateway/scripts/run_regression_suite.py`, `Gateway/scripts/run_dataset_benchmark.py`, `.github/workflows/gateway-ci.yml`
  - Safety level: High
  - Suggested wording: “The system is instrumented with a run-package-based evaluation and regression workflow rather than only ad hoc demos.”
- Claim 4: The backend exposes multi-provider abstraction and explicitly distinguishes mock/reference/http/local/real/fallback truth states.
  - Evidence: `Gateway/services/inference_service/providers/__init__.py`, `Gateway/main.py:3721`, `Gateway/main.py:4062`, `ByesPcaFrameSource.cs`, `ByesPassthroughController.cs`
  - Safety level: High
  - Suggested wording: “The repository exposes provider truth and capability state explicitly, which makes the prototype auditable under mixed real/mock/fallback deployments.”
- Claim 5: The current shared event pipeline already integrates multiple assistive perception modules, including OCR, detection/find, risk sensing, depth, overlay return, and target tracking.
  - Evidence: `Gateway/main.py:1553`, `Gateway/main.py:1710`, `Gateway/main.py:1772`, `Gateway/main.py:1900`, `Gateway/main.py:4889`, `Gateway/main.py:4907`
  - Safety level: Medium
  - Suggested wording: “The current prototype already integrates multiple assistive perception modules in a shared event pipeline.”
- Claim 6: The Quest-side prototype includes hand/controller interaction layers and passthrough/HUD integration rather than only a desktop demo.
  - Evidence: `ByesHandMenuController.cs`, `ByesHandGestureShortcuts.cs`, `ByesPassthroughController.cs`
  - Safety level: Medium
  - Suggested wording: “The prototype includes on-device interaction layers tailored for Quest hand/controller usage.”

## 10. What Must Not Be Written, or Must Be Written Conservatively
- Must not write: “The system already implements a mature open-vocabulary detection/segmentation method.”
  - Why not: the repo has prompt-conditioned DET/SEG interfaces and external-service wrappers, but not enough evidence for a mature open-vocabulary method or paper-grade results.
  - Minimum work needed: fixed provider setup, standard benchmark, quantitative results, and failure cases.
- Must not write: “The system achieves real-time low latency on Quest and clearly outperforms baselines.”
  - Why not: the repo contains latency instrumentation and reporting scripts, but not a formal result table ready to cite.
  - Minimum work needed: real hardware latency table with P50/P90/P99, provider configurations, and baseline comparisons.
- Must not write: “The system already closes a full 3D mapping/SLAM navigation loop.”
  - Why not: current evidence is closer to SLAM pose/trajectory integration plus service proxies and TUM evaluation hooks.
  - Minimum work needed: fixed SLAM backend, online trajectory evidence, and proof that the frontend consumes it in user tasks.
- Must not write: “The system already performs active perception / view-planning online.”
  - Why not: current POV code lives mainly in run-package/context/planner paths; no live camera-control or view-execution main path was found.
  - Minimum work needed: online policy -> viewpoint action -> perception gain loop plus experiments.
- Must not write: “The system already supports hand-eye coordination.”
  - Why not: hand-related code is for menu input, gesture shortcuts, and modality switching, not an assistive hand-eye task controller.
  - Minimum work needed: define the task, implement the control logic, and evaluate it.
- Must not write: “VLM/VLA is the core controller of the current Quest workflow.”
  - Why not: planner and `RealVlmTool` exist, but the Quest smoke main scene does not clearly route through the plan client/executors.
  - Minimum work needed: integrate `/api/plan` -> action execution -> confirm loop on the main scene and evaluate it.
- Must write conservatively: “edge-cloud collaboration.”
  - Why only conservatively: the architecture supports it, but there are no systematic deployment/performance/fault-tolerance results.
  - Minimum work needed: fixed deployment topology plus offline/degraded/network-failure experiments.
- Must write conservatively: “safety.”
  - Why only conservatively: runtime guardrails exist, but no user-safety results, ethics evaluation, or full privacy pipeline was found.
  - Minimum work needed: false-positive/false-negative safety experiments, human factors, privacy/compliance description.
- Must not write: “user studies already show the system is effective.”
  - Why not: no repo evidence was found.
  - Minimum work needed: IRB/ethics, study protocol, participant data, statistics.

## 11. Most Missing Experiments, Figures, Tables, and Logs
- P0: Real Quest end-to-end latency and failure-rate experiments.
  - Why: without this, a “low-latency real-time assistive” result claim is not defensible.
  - Best section: `Experiments`
- P0: Core task result table under fixed provider configurations.
  - Contents: OCR, DET/find, risk, depth, segmentation, SLAM, frame-e2e.
  - Best section: `Experiments`
- P0: Main-path ablations for gating and degradation.
  - Contents: scheduler preempt on/off, EventGuard on/off, LocalSafetyFallback on/off, provider real/mock/fallback.
  - Best section: `Experiments` / `Low-Latency Co-Design`
- P0: Frozen configuration snapshot and capability-truth record for the actual main-scene experiment setup.
  - Why: provider selection is highly configurable, so results will not be reproducible otherwise.
  - Best section: `Implementation` / `Appendix`
- P1: Planning-context and safety-kernel ablations.
  - Contents: POV/SEG/SLAM/costmap context on/off, guardrails on/off, fallback-used rate.
  - Best section: `Experiments`
- P1: SLAM and costmap quality evaluation.
  - Contents: TUM ATE/RPE, tracking rate, fused-costmap stability/flicker/shift-gate metrics.
  - Best section: `Experiments`
- P1: Failure-case gallery.
  - Contents: failed find prompts, bad seg masks, depth failures, SLAM lost cases, fallback activation.
  - Best section: `Discussion / Limitation`
- P1: Long-run stability logs.
  - Contents: reconnect counts, safe-mode enters, preempt counts, throttle counts, event drop rates.
  - Best section: `Experiments` / `Appendix`
- P2: Interaction burden and confirm/haptic statistics.
  - Best section: `Discussion`
- P2: Energy, bandwidth, and asset-fetch overhead.
  - Best section: `Experiments` / `Appendix`

## 12. Figure and Table Suggestions
- System overview figure
  - Draw: Quest-side capture/interaction, Gateway, standalone services, run-package/report pipeline.
  - Use repo content from: `Quest3SmokeScene`, `ScanController`, `GatewayClient`, `Gateway/main.py`, `services/*`, `recording/manager.py`, `report_run.py`.
- Data-flow / timing figure
  - Draw: `scan -> /api/frame -> scheduler + _run_inference_for_frame -> ws/assets -> HUD/TTS/haptics -> /api/frame/ack`.
  - Use repo content from: `ScanController`, `Gateway/main.py`, `ByesVisionHudRenderer`, `SpeechOrchestrator`.
- Module status table
  - Draw: `Implemented / Partially Implemented / Documented but Not Implemented / Missing` for each major target module.
  - Use repo content from: Section 4 of this audit.
- Low-latency pipeline figure
  - Draw: FAST/SLOW lanes, TTL, cancel-older-frame behavior, preempt window, EventGuard, LocalSafetyFallback.
  - Use repo content from: `Gateway/byes/scheduler.py`, `EventGuard.cs`, `LocalSafetyFallback.cs`, `LocalActionPlanGate.cs`.
- Failure-case figure
  - Draw: OCR misses, find-concept false detections, bad seg masks, depth/SLAM unavailable cases, fallback overlays.
  - Use repo content from: run-package fixtures, historical artifacts, overlay asset dumps.
- Ablation table
  - Draw: scheduler/preempt/fallback/plan-context/safety-kernel on-off comparisons.
  - Use repo content from: `ablate_planner.py`, `sweep_plan_context_pack.py`, `run_dataset_benchmark.py`.
- End-to-end performance table
  - Draw: `riskLatencyP90`, `frame_e2e_p90`, OCR CER, segmentation F1, depth AbsRel, SLAM ATE/RPE, costmap stability.
  - Use repo content from: `report_run.py`, `run_dataset_benchmark.py`, `eval_slam_tum.py`.

## 13. Paper-Writing Suggestions
- Best paper positioning:
  - systems paper / prototype / engineering-heavy assistive AI systems paper
  - not recommended as a pure algorithms paper
- Safer title directions (3):
  - `Be Your Eyes: A Quest-Based Assistive Vision Prototype with Auditable Runtime Feedback and Evaluation`
  - `Be Your Eyes: An End-to-End Assistive Vision System Prototype with Mode-Aware Scheduling and Run-Package Evaluation`
  - `Be Your Eyes: A Mixed Reality Assistive Perception Prototype with Safety Fallbacks and Multi-Provider Integration`
- Two good contribution organizations:
  - Track A: `System + Runtime`
    - end-to-end Quest-Gateway prototype
    - mode-aware async scheduling and safety fallback
    - multi-provider perception integration
    - run-package evaluation stack
  - Track B: `Prototype + Toolchain`
    - assistive interaction frontend
    - backend orchestration and capability truth
    - replay/report/regression infrastructure
    - preliminary module-level evaluation
- Most likely reviewer attack points:
  - The structure is visibly transitional and looks like two generations of the system coexist.
  - Any low-latency/safety/user-value claim without formal results will be attacked immediately.
  - Active perception, hand-eye coordination, VLM/VLA, and SLAM are high-risk if overstated.
  - Provider choices are highly configurable; without frozen experiment configs, reproducibility will be questioned.

## 14. Claim-Evidence Matrix
| claim | evidence | confidence | can write now? | what is still missing? |
| --- | --- | --- | --- | --- |
| The repo contains a Unity/Quest frontend prototype | `Quest3SmokeScene`, `ByesQuest3ConnectionPanelMinimal`, `ByesHandMenuController` | High | yes | nothing |
| `Quest3SmokeScene` is the current build scene | `ProjectSettings/EditorBuildSettings.asset:9` | High | yes | nothing |
| Quest can capture frames and upload them to Gateway | `ScanController`, `ByesPcaFrameSource`, `/api/frame` | High | yes | device run logs/screenshots would strengthen it |
| The system supports websocket event return | `GatewayClient.HandleWsMessage`, `/ws/events` | High | yes | nothing |
| The system supports overlay asset fetch and Quest HUD rendering | `ByesVisionHudRenderer`, `/api/assets/{asset_id}` | High | yes | runtime screenshots |
| Gateway is the central backend aggregator | `Gateway/main.py` with `/api/frame`, `/api/assist`, `/api/plan`, `/api/record/*`, `/ws/events` | High | yes | nothing |
| The backend has asynchronous dual-lane scheduling | `Gateway/byes/scheduler.py` FAST/SLOW queues | High | yes | scheduling experiments |
| The backend also retains a direct inference-v1 path | `submit_frame -> scheduler.submit_frame -> _run_inference_for_frame` | High | yes | nothing |
| OCR is a real integrated capability | `inference_service /ocr`, PaddleOCR provider, Quest read flow | High | yes | formal results |
| Detection/find is a real integrated capability | `/api/assist`, `UltralyticsDetProvider`, `det.objects.v1`, `target.update` | High | yes | quantitative quality results |
| Mature open-vocabulary detection is already integrated | only prompt-conditioned class filtering and prompt metadata are evident | Medium | no | fixed method, benchmark, results |
| Segmentation is integrated | `http_seg`, `sam3_seg_service`, `seg.mask.v1` | Medium | careful | frozen main-path config and results |
| Depth is integrated | `onnx_depth`, `da3_depth_service`, `depth.map.v1` | High | yes | formal results |
| SLAM pose integration exists | `/slam/pose`, `reference_slam_service`, `pyslam_service`, `eval_slam_tum.py` | Medium | careful | fixed backend and user-facing loop evidence |
| Costmap and fused-costmap are implemented | `CostmapFuser`, `map.costmap`, `map.costmap_fused` | Medium | careful | Quest-side consumption and results |
| The system has run-package recording/replay/report infrastructure | `RecordingManager`, `report_run.py`, `run_regression_suite.py` | High | yes | nothing |
| The system has runtime safety guardrails | `LocalSafetyFallback`, `LocalActionPlanGate`, `SafetyKernel` | High | yes | user-safety experiments |
| The system has a planner/action-plan backend | `/api/plan`, `planner_service`, `PlanClient` | High | careful | real integration on the main Quest scene and results |
| The current Quest smoke scene uses planner as a default main path | scene search found no `PlanClient`/`PlanExecutor`/`ActionPlanExecutor` | High | no | integrate and validate on the main scene |
| Hand input is already used for Quest UI interaction | `ByesHandGestureShortcuts`, `ByesHandMenuController`, `ByesWristMenuAnchor` | High | yes | nothing |
| Hand-eye coordination is implemented | only hand-input UI exists; no assistive hand-eye task loop found | Medium | no | task definition, control logic, results |
| Active perception is running online | POV/plan-context code exists, but no online camera-control path was found | Medium | no | online implementation and experiments |
| The repo contains training code | repo-wide search found no explicit training entrypoint | High | no | training code or explicit external-training statement |
| The repo already contains user-study results | no such evidence found | High | no | study protocol and data |

## 15. Appendix: Key Evidence Index
- Unity scene and bootstrap:
  - `Assets/Scenes/Quest3SmokeScene.unity`
  - `Assets/BeYourEyes/AppBootstrap.cs`
  - `Assets/Scripts/BYES/Core/ByesRuntimeBootstrap.cs`
- Unity main-path components:
  - `Assets/BeYourEyes/Unity/Interaction/ScanController.cs`
  - `Assets/Scripts/BYES/Quest/ByesPcaFrameSource.cs`
  - `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs`
  - `Assets/BeYourEyes/Adapters/Networking/GatewayFrameUploader.cs`
  - `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`
  - `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs`
  - `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs`
  - `Assets/Scripts/BYES/Quest/ByesPassthroughController.cs`
  - `Assets/BeYourEyes/Presenters/Audio/SpeechOrchestrator.cs`
  - `Assets/BeYourEyes/Unity/Interaction/LocalSafetyFallback.cs`
  - `Assets/BeYourEyes/Adapters/Networking/LocalActionPlanGate.cs`
  - `Assets/BeYourEyes/Adapters/Networking/EventGuard.cs`
- Gateway main path:
  - `Gateway/main.py`
  - `GatewayApp.submit_frame`
  - `GatewayApp._run_inference_for_frame`
  - `/api/frame`, `/api/assist`, `/api/plan`, `/api/record/start`, `/api/record/stop`, `/ws/events`
- Gateway core submodules:
  - `Gateway/byes/scheduler.py`
  - `Gateway/byes/safety_kernel.py`
  - `Gateway/byes/plan_pipeline.py`
  - `Gateway/byes/mapping/costmap_fuser.py`
  - `Gateway/byes/recording/manager.py`
  - `Gateway/byes/target_tracking/store.py`
  - `Gateway/byes/target_tracking/manager.py`
- Standalone services:
  - `Gateway/services/inference_service/app.py`
  - `Gateway/services/inference_service/providers/__init__.py`
  - `Gateway/services/planner_service/app.py`
  - `Gateway/services/planner_service/pov_adapter.py`
  - `Gateway/services/reference_slam_service/app.py`
  - `Gateway/services/pyslam_service/app.py`
  - `Gateway/services/sam3_seg_service/app.py`
  - `Gateway/services/da3_depth_service/app.py`
- Evaluation/reporting:
  - `Gateway/scripts/report_run.py`
  - `Gateway/scripts/run_regression_suite.py`
  - `Gateway/scripts/run_dataset_benchmark.py`
  - `Gateway/scripts/eval_slam_tum.py`
  - `Gateway/tests/fixtures`
  - `Gateway/artifacts/run_packages`
