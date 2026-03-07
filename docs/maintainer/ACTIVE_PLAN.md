# ACTIVE_PLAN

Canonical active execution plan.
- Source: approved `v5.07 True Capture + True Voice` design from maintainer discussion on `2026-03-07`.
- Updated: `2026-03-07`.
- Scope: current approved version plan until superseded by a newer maintainer decision.

## Current Version Goal

- Make capture truth explicit everywhere: Quest panel, Desktop Console, `/api/capabilities`, `/api/providers`, and `/api/ui/state` may only surface `pca_real`, `ar_cpuimage_fallback`, `rendertexture_fallback`, or `unavailable`.
- Deliver a true-voice evidence loop: Quest mic capture -> Gateway ASR truth -> transcript/action ack -> Quest-visible state, plus Quest-local TTS truth with visible spoken or muted evidence.
- Keep Quest and Desktop aligned on `real / mock / fallback / unavailable / muted` semantics for capture, ASR, and TTS.
- Extend smoke validation with capture-truth checks and voice evidence visibility without changing contracts, inference-provider semantics, or replay/report/regression logic.
- Preserve the v5.06 interaction boundary: no new primary entry, no Hand Menu IA rewrite, and pySLAM remains optional outside the default mainline.

## Files to Modify

- `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs`
- `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`
- `Assets/Scripts/BYES/Quest/ByesPcaFrameSource.cs`
- `Assets/Scripts/BYES/Quest/ByesRenderTextureFrameSource.cs`
- `Assets/BeYourEyes/Unity/Interaction/ScanController.cs`
- `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs`
- `Assets/Scripts/BYES/Quest/ByesQuest3SelfTestRunner.cs`
- `Assets/Scripts/BYES/Quest/ByesVoiceCommandRouter.cs` (only if transcript-to-action evidence needs a minimal fix)
- `Assets/BeYourEyes/Presenters/Audio/SpeechOrchestrator.cs`
- `Assets/BeYourEyes/Presenters/Audio/AndroidTtsBackend.cs` (only if TTS truth needs a platform-specific fix)
- `Gateway/main.py`
- `Gateway/byes/asr.py`
- `VERSION`
- `README.md`
- `docs/maintainer/WORKFLOW_HANDOFF.md`
- `docs/maintainer/ARCHITECTURE_REVIEW.md`
- `docs/maintainer/ACTIVE_PLAN.md`
- `docs/maintainer/REPO_FACTS.json`
- `docs/maintainer/DECISIONS.md`
- `docs/English/RELEASE_NOTES.md`
- `docs/Chinese/RELEASE_NOTES.md`
- `tools/quest3/quest3_usb_realstack_v5_05.cmd` (only if launcher defaults need to reflect ASR/TTS truth evidence)

## Files or Modules Explicitly Not Touched

- `Gateway/contracts/contract.lock.json`
- `Gateway/contracts/byes.event.v1.json`
- `Gateway/contracts/frame.input.v1.json`
- `Gateway/contracts/frame.ack.v1.json`
- `Gateway/services/inference_service/providers/paddleocr_ocr.py`
- `Gateway/services/inference_service/providers/ultralytics_det.py`
- `Gateway/services/inference_service/providers/sam3_seg.py`
- `Gateway/services/inference_service/providers/da3_depth.py`
- `Gateway/services/inference_service/providers/onnx_depth.py`
- `Gateway/byes/recording/manager.py`
- `Gateway/scripts/replay_run_package.py`
- `Gateway/scripts/report_run.py`
- `Gateway/scripts/run_regression_suite.py`
- `Assets/Scripts/BYES/Quest/ByesPassthroughController.cs`
- `Assets/Scenes/Quest3SmokeScene.unity`
- `Assets/Prefabs/BYES/Quest/BYES_HandMenu.prefab`
- `Assets/Prefabs/BYES/Quest/BYES_WristMenu.prefab`

## Quest Manual Acceptance Steps

1. Run `tools\quest3\quest3_usb_realstack_v5_05.cmd` and confirm the desktop console at `/ui` is reachable.
2. Launch `Quest3SmokeScene` on Quest and confirm `BYES_HandMenu` remains the only primary entry and Smoke Panel stays a status surface.
3. Check Quest panel and Desktop Console for `HTTP`, `WS`, `mode`, `record state`, and provider truth; they must match.
4. Verify frame source is shown as exactly one of `pca_real`, `ar_cpuimage_fallback`, `rendertexture_fallback`, or `unavailable`, with a visible reason when not real.
5. Trigger `Scan Once` and confirm Quest panel, HUD, and Desktop Console agree on frame-source truth and the latest capture success timestamp.
6. Run a push-to-talk ASR request and confirm transcript, ASR backend truth, and triggered action ack are visible on both Quest and Desktop.
7. Run `Speak Test` and `Beep Test` and confirm `Last Spoken`, `TTS muted`, and TTS backend truth are visible and consistent on both Quest and Desktop.
8. Run `SelfTest` and confirm there is no regression in capture truth, `HTTP`, `WS`, `mode`, `OCR`, `DET`, `TTS`, `ASR`, or HUD asset flow.

## Required Gates

```bash
python tools/check_docs_links.py
python tools/check_unity_meta.py
python tools/check_unity_layering.py
python tools/check_unity_legacy_input.py
cd Gateway && python -m pytest -q -n auto --dist loadgroup
cd Gateway && python scripts/lint_run_package.py --run-package tests/fixtures/run_package_with_events_v1_min
cd Gateway && python scripts/run_regression_suite.py --suite regression/suites/baseline_suite.json --baseline regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
cd Gateway && python scripts/run_regression_suite.py --suite regression/suites/contract_suite.json --baseline regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
cd Gateway && python scripts/verify_contracts.py --check-lock
cmd /c tools\unity\build_quest3_android.cmd
tools\quest3\quest3_usb_realstack_v5_05.cmd
```

## Main Risks and Rollback Plan

- Main risk: capture truth and voice truth drift apart again across Quest panel, self-test, `/api/capabilities`, `/api/providers`, `/api/ui/state`, and Desktop Console.
- Secondary risk: attempting to surface "true" capture or voice evidence accidentally breaks the existing fallback chain or TTS/ASR smoke path.
- Rollback rule: keep contracts and old fields intact; prefer additive truth fields, mapping layers, and one-version compatibility over destructive rewrites.
- First rollback targets if Quest smoke regresses: `Gateway/main.py`, `Gateway/byes/asr.py`, `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`, `Assets/BeYourEyes/Unity/Interaction/ScanController.cs`, and `Assets/BeYourEyes/Presenters/Audio/SpeechOrchestrator.cs`.
