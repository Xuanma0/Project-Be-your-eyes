# PAPER_SOURCE_MARKDOWN_FOR_BE_YOUR_EYES

## 1. Paper Positioning
- Best-fit paper type:
  - Primary: systems paper / prototype
  - Secondary: engineering-oriented systems paper
  - Not recommended: algorithm paper
- Why:
  - The strongest evidence is not a new model, a new training method, or a new loss. It is an end-to-end assistive vision prototype from a Quest/Unity frontend to a Python Gateway backend.
  - The most solid parts of the repository are the main system path, asynchronous scheduling, safety degradation, observability, recording/replay, and the evaluation toolchain, rather than algorithmic novelty.
  - OCR, detection/find, risk, depth, segmentation, SLAM pose, HUD, TTS/haptics, and recording/reporting all have code evidence, but many of them are still "integrated" rather than "systematically validated."
- Safest submission narrative:
  - Frame the paper as "a Quest-to-Gateway end-to-end assistive vision system prototype for accessibility scenarios," with the core contribution being the organization of capture, perception, feedback, scheduling, and evaluation into one auditable runtime.
  - The main paper body can focus on: the Quest main path, Gateway aggregation, mode-aware asynchronous scheduling, local fallback, provider truth/capability exposure, and the run-package toolchain.
  - Limitation / ongoing work can include: making planner/VLM a default path, POV/context-driven active perception, user-facing costmap closure, user-facing SLAM closure, and quantified low-latency benefit.
  - Still not writable: SOTA claims, user benefit claims, validated real-time claims, mature active perception, mature hand-eye coordination, and a complete VLM/VLA control loop.

## 2. Candidate Titles (5)
- System-oriented 1: `Be Your Eyes: A Quest-to-Gateway Assistive Vision Prototype with Auditable Runtime Feedback`
- System-oriented 2: `Be Your Eyes: An End-to-End Assistive Vision System Prototype with Mode-Aware Scheduling and Safety Fallbacks`
- System-oriented 3: `Be Your Eyes: A Run-Package-Centric Assistive Perception Prototype for Mixed Reality`
- Method-oriented 1: `Mode-Aware Asynchronous Perception and Safety Co-Design for Assistive Mixed Reality`
- Assistive AI / egocentric vision 1: `Be Your Eyes: An Assistive Egocentric Vision Prototype for Quest-Based Perception and Feedback`

## 3. One-Sentence Paper Claim
- Conservative:
  - We implement a Quest-to-Gateway assistive vision prototype that organizes head-mounted image capture, backend multi-module perception, and visual/speech/haptic feedback into one runtime loop.
- Balanced:
  - We present a Quest-based end-to-end prototype for assistive vision that unifies perception, feedback, and evaluation under a mode-aware asynchronous runtime with local safety degradation and multi-provider integration.
- More ambitious but still honest:
  - We show an auditable head-mounted assistive vision prototype whose main contribution is not a single model, but the end-to-end organization of multi-module perception, low-latency runtime design, safety interaction, and a run-package-based evaluation stack.

## 4. Abstract Material Pool
- Background:
  - Head-mounted assistive vision systems require not only perception capability, but also stable runtime organization, controllable feedback, and inspectable system behavior.
  - In assistive settings, system value depends on whether capture, inference, feedback, and degradation can work together inside one loop, rather than on single-model accuracy alone.
- Problem:
  - The engineering problem reflected by this repository is how to organize Quest-side visual capture, backend multi-module inference, and multimodal feedback into a runnable, auditable, replayable assistive system prototype.
  - The challenge lies not only in model invocation, but also in mode switching, asynchronous scheduling, event staleness, safety degradation, and mixed real/external/mock provider state management.
- Method:
  - We adopt a Quest-to-Gateway system organization that unifies frame capture, task triggering, backend scheduling, event aggregation, and feedback rendering into a single event chain.
  - The backend manages multi-capability coordination through mode-aware scheduling, FAST/SLOW queues, TTL, preemption, provider truth-state, and fallback mechanisms.
- System:
  - The frontend is composed of `Quest3SmokeScene`, `ByesQuest3ConnectionPanelMinimal`, `ScanController`, `GatewayClient`, `ByesVisionHudRenderer`, `ByesHandMenuController`, and related components for capture, upload, event reception, and user feedback.
  - The backend, centered on `Gateway/main.py`, exposes `/api/frame`, `/ws/events`, `/api/assist`, `/api/plan`, `/api/record/*`, `/api/assets/{asset_id}`, `/api/asr`, and related interfaces, and connects to separate inference/planner/SLAM services.
- Key design:
  - The key design is not a new single model. It is the explicit runtime organization of mode-aware scheduling, event TTL/reorder guards, local `LocalSafetyFallback`, `LocalActionPlanGate`, and provider capability/truth-state.
  - The system also uses run-packages as a unified observation carrier that connects online execution, offline reporting, replay, benchmarking, and regression testing.
- Implementation:
  - The current codebase clearly integrates OCR, detection/find, risk, depth, segmentation, SLAM pose, target tracking, HUD overlay, TTS/haptics, and recording/reporting paths.
  - Planning, POV/context, costmap, and VLM-related paths also exist, but some of them are not yet the default user path in the Quest smoke scene.
- Results:
  - [待补结果] The repository already contains benchmark scripts, latency instrumentation, TUM SLAM evaluation, report generation, and regression scripts, but the audit did not extract formal quantitative results ready to be written into an abstract.
  - [待补结果] If this is submitted as a paper, any abstract-level statement about performance, latency, robustness, or user benefit must wait for added experiments.
- Significance:
  - This work is best framed as an auditable assistive AI system prototype rather than a single-module algorithm contribution.
  - The repository already provides a writable system storyline, traceable code evidence, and extensible experimental hooks for a paper draft.

## 5. Introduction Material Pool
### 5.1 Research Question
- How can Quest-side visual capture, mode interaction, backend multi-capability perception, HUD/speech/haptic feedback, and a record/replay toolchain be organized into a truly runnable assistive vision prototype, rather than a loose collection of scripts and services?
- How can a system-level design simultaneously handle asynchrony, mode switching, capability degradation, event expiration, and safety fallback?

### 5.2 Why It Is Hard
- The code reality shows a system spanning Unity/Quest, Gateway, standalone services, and WebSocket/HTTP communication layers, with many runtime boundaries and many state sources.
- The repository includes local providers, HTTP wrappers, mocks, reference paths, and fallback paths. The system must explicitly represent whether a capability is actually available, rather than assume ideal conditions.
- In assistive settings, failure is not only a perception error. It also includes latency, stale events, link interruption, unavailable providers, and unsafe feedback.

### 5.3 What Existing Approaches Miss
- If the paper is written only around a detector, an OCR module, or a VLM endpoint, it cannot explain how an assistive system works coherently at runtime.
- What this repository most strongly supports is not a single model contribution, but runtime orchestration: what runs first, what can degrade, which outputs can be dropped, when safe mode is entered, and how system behavior is recorded and replayed.

### 5.4 Our Core Idea
- Structure the system into four layers: Quest-side capture and interaction, Gateway-side unified orchestration, a replaceable provider/external service layer, and a run-package-driven observation/evaluation layer.
- Treat low latency and safety as runtime coordination problems rather than offline model problems, handled jointly through FAST/SLOW queues, TTL, preemption, event filtering, and local fallback.

### 5.5 What We Built
- We implemented a runnable Quest smoke main path covering scan, mode switching, read/find, HUD, speech, and haptic feedback.
- We implemented a unified Gateway aggregation layer exposing frame ingest, assist, plan, record, asset, websocket event, confirm, and ASR interfaces.
- We implemented multi-provider perception integration, target tracking, recording, run-package reporting, benchmarking, and regression tooling.

### 5.6 Contributions Actually Supported by the Current Code
- End-to-end prototype: the main path from Quest frame capture to Gateway inference, then event return, overlay fetching, and user-side feedback is explicitly present.
- Runtime design: mode-aware scheduling, FAST/SLOW queues, TTL, preemption, `LocalSafetyFallback`, `LocalActionPlanGate`, and `EventGuard` are all concretely implemented.
- Observability: run-package recording, replay, reporting, benchmarking, regression scripts, and CI support system-level inspectability rather than one-off demos.
- Capability integration: OCR, risk, depth, segmentation, SLAM pose, and target tracking are integrated, but not all with the same level of main-path maturity.

### 5.7 Scope and Honest Boundary
- Already safe to write into the main paper body:
  - The Quest-to-Gateway system prototype.
  - Unified Gateway aggregation and multi-interface exposure.
  - Mode-aware asynchronous scheduling and local safety degradation.
  - Run-package-centered observation, reporting, and regression workflow.
- Suitable only for limitation / ongoing work:
  - Planner/VLM as a default path in the Quest main chain.
  - POV/context-driven active perception.
  - User-facing costmap closure.
  - User-facing SLAM closure.
  - Quantified benefit of edge/cloud split and low-latency design.
- Still not writable:
  - User study conclusions.
  - SOTA or performance-leading claims.
  - Validated real-time claims.
  - Mature active perception, mature hand-eye coordination, or mature VLM/VLA control loops.

## 6. Contribution Framing (Most Important)
### Template A: System-Oriented
1. We implement a Quest-to-Gateway end-to-end assistive vision prototype that places head-mounted capture, backend perception, HUD/speech/haptic feedback, and user-side acknowledgment inside one runtime loop.  
`Evidence strength: High`  
`Recommended for abstract: Yes`  
`Recommended for contribution list: Yes`

2. We design and implement a mode-aware asynchronous runtime including FAST/SLOW scheduling, TTL, a preemption window, event filtering, and local fallback.  
`Evidence strength: High`  
`Recommended for abstract: Yes`  
`Recommended for contribution list: Yes`

3. We unify multi-provider perception integration and capability/truth-state exposure inside one Gateway framework, making real, mock, reference, fallback, and external-service states explicit.  
`Evidence strength: High`  
`Recommended for abstract: Yes`  
`Recommended for contribution list: Yes`

4. We build a run-package-driven workflow for recording, replay, reporting, benchmarking, and regression, supporting system-level analysis rather than one-off demos.  
`Evidence strength: High`  
`Recommended for abstract: Yes`  
`Recommended for contribution list: Yes`

5. We integrate OCR, detection/find, risk, depth, segmentation, SLAM pose, target tracking, and multimodal feedback as composable capabilities in the current system path.  
`Evidence strength: Medium`  
`Recommended for abstract: Yes`  
`Recommended for contribution list: Yes`

### Template B: Method + System Co-Design
1. We propose a mode-aware runtime co-design for assistive vision prototypes, jointly treating perception triggering, event timeliness control, and safety feedback as part of the system path.  
`Evidence strength: High`  
`Recommended for abstract: Yes`  
`Recommended for contribution list: Yes`

2. We implement a unified integration path for prompt-conditioned detection/find and target tracking, allowing scan-find-track-feedback to run inside one event chain.  
`Evidence strength: Medium`  
`Recommended for abstract: Yes`  
`Recommended for contribution list: Yes`

3. We implement a context-pack-based planning interface and constrain planning outputs through guardrails and fallback mechanisms.  
`Evidence strength: Medium`  
`Recommended for abstract: No`  
`Recommended for contribution list: Yes`

4. We organize segmentation, depth, SLAM, costmap, and POV context into a unified backend analysis path, leaving a common interface for system-level planning and offline evaluation.  
`Evidence strength: Medium`  
`Recommended for abstract: No`  
`Recommended for contribution list: Yes`

5. We provide an auditable experimental interface layer so that latency, OCR, segmentation, depth, SLAM, and costmap metrics can be generated within one run-package framework.  
`Evidence strength: High`  
`Recommended for abstract: Yes`  
`Recommended for contribution list: Yes`

## 7. Paper Structure Mapping
### 1 Introduction
- What to write:
  - Explain that the challenge of head-mounted assistive vision is not single-model invocation, but system-level runtime organization.
  - Introduce the paper as a runnable prototype with an auditable runtime and replayable evaluation.
- Which repo evidence supports it:
  - `Assets/Scenes/Quest3SmokeScene.unity`
  - `Assets/BeYourEyes/Unity/Interaction/ScanController.cs`
  - `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs`
  - `Gateway/main.py`
  - `Gateway/byes/scheduler.py`
  - `Gateway/byes/recording/manager.py`
- What is still missing:
  - [待补实验] No formal result yet to support why this organization is better.
  - [待补证据] No user-task evidence yet.

### 2 Related Work
- What to write:
  - Compare against assistive AI, egocentric vision, MR assistive interfaces, agent/runtime orchestration systems, and edge-cloud collaboration systems.
  - Emphasize that the contribution is not a new perception model, but runtime organization and system auditability.
- Which repo evidence supports it:
  - System traits already confirmed in the audit: Quest frontend, Gateway aggregation, multi-provider integration, run-packages, planner/POV/costmap interfaces.
- What is still missing:
  - [待补证据] External literature must be added by the authors; this is not repo evidence.

### 3 System Overview
- What to write:
  - Summarize the roles of the frontend, backend, communication layer, provider layer, and run-package toolchain.
  - State that the Quest smoke main path is the current most stable user path.
- Which repo evidence supports it:
  - `Quest3SmokeScene.unity`
  - `ByesQuest3ConnectionPanelMinimal.cs`
  - `ScanController.cs`
  - `GatewayClient.cs`
  - `Gateway/main.py`
  - `Gateway/services/*`
- What is still missing:
  - [待补证据] If the paper wants a fixed deployment topology, it still needs a deployment/config snapshot.

### 4 Method / Architecture
- What to write:
  - Write the method as a system architecture method: mode-aware runtime, module triggering policy, event representation, provider wrapping, and context-pack organization.
  - Be explicit that the paper does not propose a new detector/OCR/SLAM algorithm.
- Which repo evidence supports it:
  - `Gateway/byes/scheduler.py`
  - `Gateway/byes/safety_kernel.py`
  - `Gateway/byes/plan_pipeline.py`
  - `Gateway/services/inference_service/providers/__init__.py`
  - `Gateway/byes/mapping/costmap_fuser.py`
- What is still missing:
  - [待补实验] No ablation results yet showing this architecture is better than alternatives.

### 5 Low-Latency Co-Design
- What to write:
  - Focus on FAST/SLOW dual lanes, TTL, canceling old frames, preemption, `EventGuard`, local fallback, and asset/frame caching.
  - Emphasize "low-latency-oriented design" rather than "already proven lowest latency."
- Which repo evidence supports it:
  - `Gateway/byes/scheduler.py`
  - `Assets/BeYourEyes/Adapters/Networking/EventGuard.cs`
  - `Assets/BeYourEyes/Adapters/Networking/LocalActionPlanGate.cs`
  - `Assets/BeYourEyes/Unity/Interaction/LocalSafetyFallback.cs`
  - `Gateway/byes/frame_cache.py`
  - `Gateway/byes/asset_cache.py`
- What is still missing:
  - [待补结果] No P50/P90/P99, per-module latency, or provider-configuration comparison tables yet.

### 6 Implementation
- What to write:
  - Describe how the Quest/Unity client, Python Gateway, standalone inference/planner/pySLAM services, and recording/reporting/benchmark scripts together form a complete implementation.
  - Note that the system already includes provider switching, truth-state exposure, test fixtures, and historical run-package artifacts.
- Which repo evidence supports it:
  - `Gateway/main.py`
  - `Gateway/services/inference_service/app.py`
  - `Gateway/services/planner_service/app.py`
  - `Gateway/services/pyslam_service/app.py`
  - `Gateway/scripts/report_run.py`
  - `Gateway/scripts/run_regression_suite.py`
  - `Gateway/scripts/run_dataset_benchmark.py`
- What is still missing:
  - [待补证据] A paper-ready experiment configuration table still needs to lock provider versions and switches.

### 7 Experiments
- What to write:
  - Only write the parts for which the repo already contains experimental hooks: latency, OCR, segmentation, depth, SLAM, costmap, planner context, and regression validation.
  - Results must wait until experiments are actually run and collected.
- Which repo evidence supports it:
  - `Gateway/scripts/bench_risk_latency.py`
  - `Gateway/scripts/eval_slam_tum.py`
  - `Gateway/scripts/ablate_planner.py`
  - `Gateway/scripts/sweep_plan_context_pack.py`
  - `Gateway/scripts/run_dataset_benchmark.py`
  - `Gateway/tests/fixtures/`
- What is still missing:
  - [待补结果] There are no formal paper-ready result tables yet.
  - [待补实验] There is no Quest real-device end-to-end stability evaluation yet.

### 8 Discussion / Limitation / Ethics
- What to write:
  - State clearly that planner/VLM is not yet established as the default Quest main path, active perception is not closed-loop, hand-eye coordination is not implemented, and SLAM remains closer to pose/service/evaluation hooks than a user-facing closed loop.
  - Discuss safety in assistive settings, including stale-event filtering, local safe mode, confirm/ack paths, and API key protection.
- Which repo evidence supports it:
  - `LocalSafetyFallback.cs`
  - `LocalActionPlanGate.cs`
  - `Gateway/byes/safety_kernel.py`
  - `Gateway/main.py` confirm endpoints and API-key guards
- What is still missing:
  - [待补实验] Real user study and ethics evaluation results are still missing.

### 9 Conclusion
- What to write:
  - Conclude that the prototype has already established a runnable main path, a structured runtime design, and an evaluation infrastructure.
  - Do not expand this into a claim that all envisioned modules are already mature.
- Which repo evidence supports it:
  - The end-to-end path, run-packages, scheduler, safety mechanisms, and provider wrapping.
- What is still missing:
  - [待补结果] Any performance-oriented conclusion must wait for experiments.

## 8. Method Section Material
### 8.1 Problem Formulation
- Core point:
  - Define the problem as follows: given a Quest-side frame or a user request, the system must produce structured perception outputs and multimodal feedback within a limited validity window, while remaining safe under degraded conditions.
- Code evidence:
  - `ScanController.cs`
  - `GatewayClient.cs`
  - `Gateway/main.py` with `/api/frame` and `/ws/events`
  - `LocalSafetyFallback.cs`
- Recommended writing:
  - Write the input as "ego-view frame + mode + target/prompt + source truth + runtime context," and the output as "event + overlay asset + speech/haptic + ack/record."
  - This is a system problem formulation, not a forced mathematical optimization problem.
- What must not be overstated:
  - Do not write that the paper solves general assistive navigation.
  - Do not write that it formally solves active perception and planning closure, because the evidence is not there.

### 8.2 System Overview
- Core point:
  - The system consists of four parts: the Quest frontend, the Gateway aggregation layer, the replaceable provider/standalone service layer, and the run-package toolchain.
- Code evidence:
  - `Assets/Scenes/Quest3SmokeScene.unity`
  - `ByesQuest3ConnectionPanelMinimal.cs`
  - `ScanController.cs`
  - `GatewayClient.cs`
  - `Gateway/main.py`
  - `Gateway/services/inference_service/app.py`
  - `Gateway/services/planner_service/app.py`
- Recommended writing:
  - Use one overview figure to make the capture-upload-infer-event-feedback-record path explicit.
  - Stress that `Gateway/main.py` is the unified backend entry, not one script among many.
- What must not be overstated:
  - Do not turn "multiple services exist" into "the optimal edge-cloud split has already been validated."

### 8.3 Module Instantiation
- Core point:
  - The paper's module instantiation can be organized around OCR, detection/find, risk, depth, segmentation, SLAM pose, target tracking, and HUD/TTS/haptics.
- Code evidence:
  - OCR: the OCR path in `Gateway/main.py`, `Gateway/services/inference_service/providers/paddleocr_ocr.py`
  - Detection/find: assist/open-vocab-related paths in `Gateway/main.py`, `ultralytics_det.py`
  - Risk: `Gateway/byes/safety_kernel.py`
  - Depth: `onnx_depth.py`
  - SLAM: `Gateway/services/pyslam_service/app.py`, `Gateway/scripts/eval_slam_tum.py`
  - Target tracking: `Gateway/byes/target_tracking/*`
- Recommended writing:
  - Do not present these as novel algorithmic modules. Present them as instantiated and integrated capabilities within the system.
  - A small table can indicate which ones are in the main path and which are optional/partial.
- What must not be overstated:
  - Do not describe open-vocabulary detection as a mature novel algorithm.
  - Do not describe SLAM as a complete online mapping and navigation loop.

### 8.4 Edge-Cloud Collaboration
- Core point:
  - The repository supports local Quest-side interaction and backend multi-service collaboration, and architecturally it has edge-cloud collaboration potential.
- Code evidence:
  - Quest local side: `Quest3SmokeScene.unity`, `LocalSafetyFallback.cs`
  - Gateway aggregation: `Gateway/main.py`
  - HTTP external services: `Gateway/services/inference_service/app.py`, `planner_service/app.py`, `pyslam_service/app.py`
  - Provider truth-state: `Gateway/services/inference_service/providers/__init__.py`
- Recommended writing:
  - Prefer wording such as "an architecture that supports mixed local/remote execution and explicit capability state."
  - Emphasize architectural support, not proven edge-cloud benefit.
- What must not be overstated:
  - Do not write "we prove that edge-cloud collaboration significantly reduces latency/cost," because there are no results yet.

### 8.5 Low-Latency Pipeline
- Core point:
  - The current system has explicit latency-oriented design: FAST/SLOW dual-lane scheduling, TTL, dropping old frames, preemption, `EventGuard`, asset/frame caches, and local fallback.
- Code evidence:
  - `Gateway/byes/scheduler.py`
  - `Gateway/byes/frame_cache.py`
  - `Gateway/byes/asset_cache.py`
  - `EventGuard.cs`
  - `LocalSafetyFallback.cs`
  - `LocalActionPlanGate.cs`
- Recommended writing:
  - Write this section as a co-design of runtime latency and safety, rather than a loose list of optimizations.
  - It is valid to point out that the system separates fast-path risk handling from slower-path complex analysis.
- What must not be overstated:
  - Do not write that the system achieves real-time performance or outperforms prior systems unless quantitative results are added.

### 8.6 Safety and Interaction Design
- Core point:
  - The system introduces safety-related control on both the client and backend sides: local fallback, event filtering, action gating, planner safety kernel, and confirm/ack interactions.
- Code evidence:
  - `LocalSafetyFallback.cs`
  - `LocalActionPlanGate.cs`
  - `EventGuard.cs`
  - `Gateway/byes/safety_kernel.py`
  - `Gateway/main.py` with `/api/confirm/*` and `/api/frame/ack`
  - `ByesHandMenuController.cs`
- Recommended writing:
  - Emphasize that safety policy is part of the runtime structure, not an afterthought added after model training.
  - It is safe to say the system is designed to avoid letting stale events, disconnected states, and unsafe action suggestions continue to propagate to the user side.
- What must not be overstated:
  - Do not claim clinical-grade or product-grade safety validation.

### 8.7 Implementation Details
- Core point:
  - At the implementation level, the most paper-worthy pieces are the Quest smoke main scene, the unified Gateway, standalone inference/planner/SLAM services, recording/reporting/benchmark scripts, and the rich fixture/run-package ecosystem.
- Code evidence:
  - `Assets/Scenes/Quest3SmokeScene.unity`
  - `Gateway/main.py`
  - `Gateway/services/inference_service/app.py`
  - `Gateway/services/planner_service/app.py`
  - `Gateway/services/pyslam_service/app.py`
  - `Gateway/byes/recording/manager.py`
  - `Gateway/scripts/report_run.py`
  - `Gateway/scripts/run_regression_suite.py`
  - `Gateway/tests/fixtures/`
- Recommended writing:
  - This section should highlight completeness of implementation and completeness of evaluation interfaces.
  - If space is limited, provider-specific details can move to the appendix.
- What must not be overstated:
  - Do not turn "there are scripts / there are entrypoints" into "all modules were fully validated under one unified experimental setup."

## 9. Experiment Section Material
### 9.1 What Already Exists
- There are runnable inference/service entrypoints: `Gateway/main.py`, `Gateway/services/inference_service/app.py`, `Gateway/services/planner_service/app.py`, `Gateway/services/pyslam_service/app.py`.
- There is benchmark/report/replay/regression infrastructure: `Gateway/scripts/report_run.py`, `Gateway/scripts/run_regression_suite.py`, `Gateway/scripts/run_dataset_benchmark.py`.
- There are specific evaluation hooks: `Gateway/scripts/eval_slam_tum.py`, `Gateway/scripts/bench_risk_latency.py`, `Gateway/scripts/ablate_planner.py`, `Gateway/scripts/sweep_plan_context_pack.py`.
- There are many minimal fixtures and historical run-package artifacts: `Gateway/tests/fixtures/`, `Gateway/artifacts/run_packages/`.
- There is currently no formal result table in the audit output that can be quoted directly in a paper.  
  - `[待补结果]`

### 9.2 What Is Currently Missing
- A fixed provider-configuration snapshot is missing; without it, experiments are not reproducible.
- A Quest-device end-to-end results table is missing.
- Formal ablation results for scheduler/fallback/context-pack behavior are missing.
- User study, task success rate, and subjective feedback are missing.
- Formal quantitative comparison for "edge-cloud benefit" and "low-latency benefit" is missing.  
  - `[待补实验]`

### 9.3 Experiments That Must Be Added
- P0: a core task results table under fixed providers and fixed switches.  
  - This can cover OCR, find/detection, risk, segmentation, depth, SLAM, and costmap.  
  - `[待补实验]`
- P0: Quest end-to-end latency and stability evaluation.  
  - This should include at least P50/P90/P99 from frame ingest to feedback/ack, event drop rate, and fallback entry rate.  
  - `[待补实验]`
- P0: key runtime ablations.  
  - This should include scheduler preemption on/off, `EventGuard` on/off, `LocalSafetyFallback` on/off, and real/mock/fallback provider settings.  
  - `[待补实验]`
- P1: planning/context-pack ablations.  
  - This should include POV/seg/SLAM/costmap context on/off, guardrail on/off, and fallbackUsed rate.  
  - `[待补实验]`
- P1: SLAM / costmap quality evaluation.  
  - This should include TUM ATE/RPE, tracking rate, and costmap stability.  
  - `[待补实验]`

### 9.4 Recommended Benchmark / Baseline / Metric
- Benchmark:
  - OCR, segmentation, depth, SLAM, planning, POV, and costmap can first be organized around `Gateway/tests/fixtures/` and run-package inputs.
  - SLAM can directly use the TUM path exposed by `Gateway/scripts/eval_slam_tum.py`.
- Baseline:
  - It is better not to invent external baselines. Start with runtime comparisons already supported by the repo.
  - Recommended baselines are: different providers, different runtime switches, different context-pack combinations, and different fallback strategies.  
  - `[待补结果]`
- Metric:
  - Latency: `riskLatencyP90`, `frame_e2e_p90`, event drop rate, fallbackUsed rate.
  - OCR: CER / WER, or the actual report fields used in the repo.
  - Segmentation: F1 / mask coverage.
  - Depth: AbsRel, or the actual report fields used in the repo.
  - SLAM: ATE / RPE / tracking rate.
  - Costmap: stability / flicker / shift gate.  
  - `[待补证据] The final metric fields should follow the actual report outputs`

### 9.5 Failure Cases and Ablation Suggestions
- Suggested failure cases:
  - prompt-conditioned find failure or false detection
  - segmentation mask miss or over-coverage
  - depth unavailable
  - SLAM lost / tracking reset
  - `LocalSafetyFallback` entering `STALE`, `DISCONNECTED`, or `SAFE_MODE_REMOTE`
- Suggested ablations:
  - Runtime side: scheduler preemption, TTL, `EventGuard`, `LocalSafetyFallback`, `LocalActionPlanGate`
  - Context side: POV, segmentation, SLAM, and costmap context-pack inclusion
  - Provider side: real/mock/reference/fallback switching
- Current status:
  - The repo has the interface basis for these figures and tables, but not ready-made paper results.  
  - `[待补结果]`

## 10. Figures, Tables, and Appendix Writing Material
- Figure 1:
  - Draw the full system overview: Quest-side capture and interaction, Gateway aggregation, standalone services, the provider layer, and the run-package/report toolchain.
  - Direct material can come from: `Quest3SmokeScene.unity`, `ScanController.cs`, `GatewayClient.cs`, `Gateway/main.py`, `Gateway/services/*`, `Gateway/byes/recording/manager.py`.
- Figure 2:
  - Draw the one-frame timing and low-latency pipeline: scan/read/find trigger, frame upload, scheduler FAST/SLOW path, event emission, HUD overlay, speech/haptics, ack, and record.
  - Direct material can come from: `ScanController.cs`, `Gateway/main.py`, `Gateway/byes/scheduler.py`, `EventGuard.cs`, `LocalSafetyFallback.cs`, `ByesVisionHudRenderer.cs`, `SpeechOrchestrator.cs`.
- Table 1:
  - Use it as a module-status table covering OCR, find/detection, risk, depth, segmentation, SLAM, costmap, planner, POV, hand input, HUD, and recording.
  - Suggested columns: implemented or not, in the Quest main path or not, local model / external service / classical algorithm / interface wrapper, and whether it is safe to write into the paper body.
- Table 2:
  - Use it as an experiment-design table rather than a result table.
  - Suggested columns: experiment purpose, corresponding script, input source, output metric, current status.  
  - The result column can currently stay as `[待补结果]`.
- Appendix:
  - provider configuration snapshots and truth/capability descriptions
  - the list of scenes and scripts involved in the Quest smoke main path
  - run-package schema and key fields
  - planner/context-pack field definitions
  - expanded failure-case figures, fallback-trigger logs, and API contract examples

## 11. Final Claim Boundary
- Statements that must not be written now:
  - "Our method achieves SOTA on assistive vision tasks."
  - "The system has been validated through real visually impaired user studies."
  - "The system has already demonstrated real-time performance."
  - "The system implements a complete 3D mapping / SLAM navigation loop."
  - "The system implements an online active perception / viewpoint planning loop."
  - "The system already supports hand-eye coordination."
  - "VLM/VLA is the core controller of the current Quest main workflow."
- Statements that can be written conservatively:
  - "The repository supports a mixed local/remote architecture with explicit capability state."
  - "The prototype includes mode-aware asynchronous scheduling and runtime safety fallbacks."
  - "Planning, POV/context, costmap, and SLAM-related paths are partially implemented and can be discussed as ongoing work."
  - "The system exposes hooks for latency, SLAM, and context-related evaluation."
  - If used in the main paper, these should not be paired with overly strong result-oriented wording.
- Statements that can be written confidently:
  - "The repository contains a Quest-to-Gateway end-to-end assistive vision prototype."
  - "`Gateway/main.py` serves as a unified backend entry for frame ingest, assist, planning, recording, assets, and WebSocket events."
  - "The current system includes explicit runtime safety mechanisms, including local fallback, event filtering, and planner-side guardrails."
  - "The repository includes a run-package-based recording, replay, reporting, benchmarking, and regression workflow."
  - "OCR, risk, depth, segmentation, SLAM pose, and target tracking all have explicit integration evidence in the repo, although they do not all have the same main-path maturity."

## 12. Short Briefing for the First Draft
- Do not write this as an algorithm paper. Write it as a "Quest-to-Gateway system prototype for assistive accessibility scenarios." The first paragraph should define the problem: the real difficulty of assistive vision lies in the system coordination of capture, inference, feedback, safety, and degradation, rather than in a single model. The second paragraph should explain the paper's core idea: we organize Quest-side capture, Gateway orchestration, multi-provider perception, HUD/speech/haptic feedback, and run-package-based evaluation into one runtime. The third paragraph should present the main contributions, prioritizing the end-to-end main path, mode-aware asynchronous scheduling, `LocalSafetyFallback` / `EventGuard` / `ActionPlanGate`, safety guardrails, and the run-package toolchain. In the method section, write the system overview first, then module instantiation, then low-latency and safety co-design, and then implementation. In experiments, for now only write "experimental design and interfaces"; all result positions should remain as `[待补结果]`. At minimum, reserve space for latency, a core task table, scheduler/fallback ablations, SLAM/TUM evaluation, and failure cases. In discussion, explicitly acknowledge that planner/VLM is not yet clearly the default Quest main path, and that active perception, hand-eye coordination, user-facing costmap closure, and user-facing SLAM closure should only appear as ongoing work, not as completed contributions.
