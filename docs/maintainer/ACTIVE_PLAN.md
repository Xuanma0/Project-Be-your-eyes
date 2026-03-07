# ACTIVE_PLAN

Canonical active execution plan.
- Source: approved `v5.08 True PCA + Whole-FOV Overlays + Desktop Console as Operator UI` design from maintainer discussion on `2026-03-07`.
- Updated: `2026-03-07`.
- Scope: current approved version plan until superseded by a newer maintainer decision.

## Current Version Goal

- Make `pca_real` a proof-gated runtime state. Quest panel, Desktop Console, `/api/capabilities`, `/api/providers`, and `/api/ui/state` may only surface `pca_real`, `ar_cpuimage_fallback`, `rendertexture_fallback`, or `unavailable`.
- Keep Quest rendering stable while moving DET, SEG, and DEPTH into a whole-FOV hold-style overlay path. Overlay transport remains latest-frame-wins and last-frame-hold rather than per-frame inference.
- Promote Desktop Console to operator UI using only existing APIs: `/api/frame`, `/api/assist`, `/api/record/*`, `/api/mode`, `/api/capabilities`, `/api/providers`, and `/api/ui/state`.
- Surface pySLAM realtime visibility on Quest and Desktop with explicit `backend`, `state`, `fps`, `latency`, and `root detected` evidence while keeping pySLAM optional and outside CI success criteria.
- Preserve the v5.07 truth model and existing OCR, DET, RISK, recording, and replay/report/regression mainline without touching contracts or inference-provider semantics.

## Files to Modify

- `Assets/BeYourEyes/Unity/Capture/IByesFrameSource.cs`
- `Assets/BeYourEyes/Unity/Interaction/ScanController.cs`
- `Assets/Scripts/BYES/Quest/ByesPcaFrameSource.cs`
- `Assets/Scripts/BYES/Quest/ByesRenderTextureFrameSource.cs`
- `Assets/Scripts/BYES/Quest/ByesVisionHudController.cs`
- `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs`
- `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`
- `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs`
- `Assets/Scripts/BYES/Quest/ByesQuest3SelfTestRunner.cs`
- `Assets/Editor/ByesQuest3SmokeSceneInstaller.cs`
- `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs`
- `Gateway/main.py`
- `tools/quest3/quest3_usb_realstack_v5_08.cmd`
- `VERSION`
- `README.md`
- `docs/maintainer/WORKFLOW_HANDOFF.md`
- `docs/maintainer/ARCHITECTURE_REVIEW.md`
- `docs/maintainer/ACTIVE_PLAN.md`
- `docs/maintainer/REPO_FACTS.json`
- `docs/maintainer/DECISIONS.md`
- `docs/English/RELEASE_NOTES.md`
- `docs/Chinese/RELEASE_NOTES.md`

## Files or Modules Explicitly Not Touched

- `Gateway/contracts/**`
- `Gateway/services/inference_service/providers/**`
- `Gateway/byes/recording/**`
- `Gateway/scripts/replay_run_package.py`
- `Gateway/scripts/report_run.py`
- `Gateway/scripts/run_regression_suite.py`
- `Gateway/services/pyslam_service/**`
- `Gateway/scripts/pyslam_run_package.py`
- `Assets/Scripts/BYES/Quest/ByesVoiceCommandRouter.cs`
- `Assets/BeYourEyes/Presenters/Audio/**`
- `Assets/Scripts/BYES/Quest/ByesPassthroughController.cs`
- `Assets/Scenes/Quest3SmokeScene.unity`
- `Assets/Prefabs/BYES/Quest/BYES_HandMenu.prefab`
- `Assets/Prefabs/BYES/Quest/BYES_WristMenu.prefab`

## Quest Manual Acceptance Steps

1. Run `tools\quest3\quest3_usb_realstack_v5_08.cmd` and confirm the desktop console at `/ui` is reachable.
2. Launch `Quest3SmokeScene` on Quest and confirm `BYES_HandMenu` remains the only primary entry and Smoke Panel stays a status surface.
3. Check Quest panel and Desktop Console for `HTTP`, `WS`, `mode`, `record state`, and provider truth; they must match.
4. Verify frame source is shown as exactly one of `pca_real`, `ar_cpuimage_fallback`, `rendertexture_fallback`, or `unavailable`, with a visible reason when not real.
5. Trigger `Scan Once` and confirm Quest panel, HUD, and Desktop Console agree on frame-source truth, latest capture success, and overlay kinds.
6. Trigger `Detect`, `Read Text`, or `Live` and confirm whole-FOV overlays stay visible in the headset while Desktop preview tiles update from the latest overlay assets.
7. Confirm Desktop operator buttons (`Scan Once`, `Live`, `Read Text`, `Find Door`, `Record Start`, `Record Stop`) work through existing APIs and keep Quest/Desktop state aligned.
8. Run `SelfTest` and confirm there is no regression in PCA truth, whole-FOV overlay truth, `HTTP`, `WS`, `mode`, `OCR`, `DET`, or asset flow.

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
tools\quest3\quest3_usb_realstack_v5_08.cmd
```

## Main Risks and Rollback Plan

- Main risk: `pca_real`, whole-FOV overlay state, and Desktop operator view drift apart again across Quest panel, `/api/capabilities`, `/api/providers`, `/api/ui/state`, and `/ui`.
- Secondary risk: trying to force true PCA or more frequent overlay refresh introduces capture fallback regressions, frame backlog, or Quest render hitching.
- Rollback rule: keep contracts and old fields intact; prefer additive truth fields, thin UI wrappers, and one-version compatibility over destructive rewrites.
- First rollback targets if Quest smoke regresses: `Gateway/main.py`, `Assets/Scripts/BYES/Quest/ByesPcaFrameSource.cs`, `Assets/BeYourEyes/Unity/Interaction/ScanController.cs`, `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs`, and `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`.
