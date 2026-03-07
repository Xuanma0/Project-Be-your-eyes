# ACTIVE_PLAN

Canonical active execution plan.
- Source: approved `v5.06 Truth & Focus` design from maintainer discussion on `2026-03-07`.
- Updated: `2026-03-07`.
- Scope: current approved version plan until superseded by a newer maintainer decision.

## Current Version Goal

- Unify Quest entry around `BYES_HandMenu` as the sole primary interaction entry.
- Make Quest panel, Quest HUD, Desktop Console, `/api/capabilities`, `/api/providers`, and `/api/ui/state` say the same thing about `real / mock / fallback`.
- Correct frame-source naming so fallback capture is never described as true PCA.
- Strengthen Desktop Console as a runtime fact source instead of a secondary debug page.
- Preserve the smoke mainline: do not change contracts or provider logic unless explicitly approved.

## Files to Modify

- `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs`
- `Assets/Scripts/BYES/Quest/ByesWristMenuController.cs`
- `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`
- `Assets/Editor/ByesQuest3SmokeSceneInstaller.cs`
- `Assets/Scripts/BYES/Quest/ByesPcaFrameSource.cs`
- `Assets/Scripts/BYES/Quest/ByesRenderTextureFrameSource.cs`
- `Assets/BeYourEyes/Unity/Interaction/ScanController.cs`
- `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs`
- `Gateway/main.py`
- `VERSION`
- `README.md`
- `docs/maintainer/WORKFLOW_HANDOFF.md`
- `docs/maintainer/ARCHITECTURE_REVIEW.md`
- `docs/maintainer/REPO_FACTS.json`
- `docs/maintainer/DECISIONS.md`
- `docs/English/RELEASE_NOTES.md`
- `docs/Chinese/RELEASE_NOTES.md`
- `tools/quest3/quest3_usb_realstack_v5_05.cmd` (only if launcher defaults need to reflect the same truth model)

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
- `Assets/BeYourEyes/Presenters/Audio/SpeechOrchestrator.cs`
- `Assets/Scenes/Quest3SmokeScene.unity`
- `Assets/Prefabs/BYES/Quest/BYES_HandMenu.prefab`
- `Assets/Prefabs/BYES/Quest/BYES_WristMenu.prefab`

## Quest Manual Acceptance Steps

1. Run `tools\quest3\quest3_usb_realstack_v5_05.cmd` and confirm the desktop console at `/ui` is reachable.
2. Launch `Quest3SmokeScene` on Quest and confirm the primary entry is `BYES_HandMenu`; legacy wrist menu is not the default.
3. Compare Quest panel and Desktop Console for `HTTP`, `WS`, `mode`, `record state`, and provider truth; they must match.
4. Verify frame-source text no longer implies true PCA when the runtime is using fallback or unavailable capture.
5. Trigger `Scan Once` and confirm Quest panel, HUD, and Desktop Console agree on the latest frame and latest event summary.
6. Trigger `Read Text Once` and `Detect Once` and confirm Quest-visible output matches Desktop Console provider evidence.
7. Apply one provider override from Desktop Console and confirm Quest-facing truth surfaces update consistently.
8. Run `SelfTest` and confirm there is no regression in `HTTP`, `WS`, `mode`, `OCR`, `DET`, or HUD asset flow.

## Required Gates

```bash
python Gateway/scripts/verify_contracts.py --check-lock
python Gateway/scripts/run_regression_suite.py --suite Gateway/regression/suites/baseline_suite.json --baseline Gateway/regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
python Gateway/scripts/run_regression_suite.py --suite Gateway/regression/suites/contract_suite.json --baseline Gateway/regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
python Gateway/scripts/lint_run_package.py --run-package Gateway/tests/fixtures/run_package_with_events_v1_min
python tools/check_unity_meta.py
python tools/check_docs_links.py
tools\unity\build_quest3_android.cmd
tools\quest3\quest3_usb_realstack_v5_05.cmd
```

## Main Risks and Rollback Plan

- Main risk: truth surfaces drift apart again across Quest panel, `GatewayClient`, `/api/ui/state`, self-test, and Desktop Console, especially for frame source and provider evidence.
- Secondary risk: entry unification accidentally breaks the smoke mainline in `ByesQuest3ConnectionPanelMinimal.cs` or `ByesQuest3SmokeSceneInstaller.cs`.
- Rollback rule: keep contracts and old fields intact; prefer additive truth fields and one-version compatibility over destructive rewrites.
- First rollback targets if Quest smoke regresses: `Gateway/main.py`, `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs`, `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`, and `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs`.
