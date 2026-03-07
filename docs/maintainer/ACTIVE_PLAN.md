# ACTIVE_PLAN

Canonical active execution plan.
- Source: approved `v5.08.1 Visual Truth Stabilization` hotfix scope from maintainer discussion on `2026-03-08`.
- Updated: `2026-03-08`.
- Scope: current approved version plan until superseded by a newer maintainer decision.

## Current Version Goal

- Provider truth must say the current truth. If a provider is failing, timed out, disabled, missing, or returning `503/404`, Quest Panel, Desktop Console, `/api/providers`, `/api/capabilities`, and `/api/ui/state` must show `unavailable` or `fallback`, not `real`.
- Overlay assets must behave like immutable blobs. Quest should download an overlay only when `assetId` changes, cache successful textures locally, keep last-frame hold after success, and stop retry-spamming the same failed asset id.
- Whole-FOV overlay rendering must stay visually stable. Empty DET/SEG/DEPTH layers should not render default white or red backgrounds, and Desktop preview should show `unavailable + reason` when no valid overlay asset exists.
- Hand Menu and Smoke Panel interaction must be shorter and safer: reduced page length, non-overlapping sliders and labels, better Meta system-gesture conflict isolation, and panel drag that reorients toward the HMD instead of pitching forward.
- Passthrough must either be genuinely working or clearly unavailable. Quest and Desktop should show `real`, `fallback`, or `unavailable` plus a reason, and unstable half-enabled visuals should fall back to a stable background.

## Files to Modify

- `Assets/Scripts/BYES/Quest/ByesVisionHudController.cs`
- `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs`
- `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`
- `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs`
- `Assets/Scripts/BYES/Quest/ByesQuest3SelfTestRunner.cs`
- `Assets/Scripts/BYES/Quest/ByesPassthroughController.cs`
- `Gateway/main.py`
- `VERSION`
- `docs/English/RELEASE_NOTES.md`
- `docs/Chinese/RELEASE_NOTES.md`
- `docs/maintainer/ACTIVE_PLAN.md`
- `docs/maintainer/REPO_FACTS.json`
- `docs/maintainer/WORKFLOW_HANDOFF.md`

## Files or Modules Explicitly Not Touched

- `Gateway/contracts/**`
- `Gateway/services/inference_service/providers/**`
- `Gateway/byes/recording/**`
- `Gateway/scripts/replay_run_package.py`
- `Gateway/scripts/report_run.py`
- `Gateway/scripts/run_regression_suite.py`
- `Gateway/services/pyslam_service/**`
- `Gateway/scripts/pyslam_run_package.py`
- `Assets/BeYourEyes/Unity/Capture/IByesFrameSource.cs`
- `Assets/BeYourEyes/Unity/Interaction/ScanController.cs`
- `Assets/Scripts/BYES/Quest/ByesPcaFrameSource.cs`
- `Assets/Scripts/BYES/Quest/ByesRenderTextureFrameSource.cs`
- `Assets/Scripts/BYES/Quest/ByesVoiceCommandRouter.cs`
- `Assets/BeYourEyes/Presenters/Audio/**`
- `Assets/Scenes/Quest3SmokeScene.unity`
- `Assets/Prefabs/BYES/Quest/BYES_HandMenu.prefab`
- `Assets/Prefabs/BYES/Quest/BYES_WristMenu.prefab`

## Quest Manual Acceptance Steps

1. Launch the existing realstack flow and confirm the desktop console at `/ui` is reachable.
2. Launch `Quest3SmokeScene` on Quest and confirm `BYES_HandMenu` remains the only primary entry while Smoke Panel stays a status surface.
3. Confirm Quest Panel and Desktop Console both show failing DET/SLAM providers as `unavailable` when backend calls return `503`, `404`, timeout, or disabled states.
4. Trigger `Scan Once` and then `Detect` or `Live`; verify Quest downloads a given overlay asset id once, keeps it visible locally, and does not keep re-requesting the same asset id after a success or `404`.
5. Verify whole-FOV overlay layers do not show white or red blank quads when a DET/SEG/DEPTH texture is missing or disabled.
6. Open the Hand Menu and confirm Vision, Voice, and Dev pages are shorter, sliders no longer overlap labels, and system gestures suppress conflicting UI interaction.
7. Drag the Smoke Panel only after unlocking it, then release it and confirm it faces the HMD with yaw-only alignment instead of pitching toward the floor or ceiling.
8. Toggle passthrough on and off and confirm Quest and Desktop show `real`, `fallback`, or `unavailable` with a reason, with no ambiguous half-enabled visual state.

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
```

## Main Risks and Rollback Plan

- Main risk: Quest Panel, Desktop Console, and Gateway truth surfaces drift apart again if only one surface reads normalized provider or overlay state.
- Secondary risk: overlay stale-hold, passthrough fallback, or gesture isolation logic overcorrects and suppresses legitimate rendering or interaction.
- Rollback rule: prefer additive truth fields, cached local hold behavior, and UI gating over destructive rewrites. Preserve contracts and existing provider outputs.
- First rollback targets if Quest smoke regresses: `Gateway/main.py`, `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs`, `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`, `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs`, and `Assets/Scripts/BYES/Quest/ByesPassthroughController.cs`.
