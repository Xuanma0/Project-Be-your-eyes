# ACTIVE_PLAN

Canonical active execution plan.
- Source: approved `v5.09.2 Overlay Stabilization` scope from maintainer discussion on `2026-03-09`.
- Updated: `2026-03-09`.
- Scope: current approved version plan until superseded by a newer maintainer decision.

## Current Version Goal

- Stabilize overlay semantics after `v5.09.1`: keep `seg.truthState=real` when inference succeeds but returns no mask, while explicitly surfacing `overlayAvailable=false` and `overlayReason=no_segments`.
- Preserve `depth` as the minimum visible whole-FOV success layer, and do not let a single `seg=no_segments` frame degrade the overall overlay verdict.
- Keep Gateway as the single source of truth for `backend`, `model`, `device`, `deviceReason`, `truthState`, `overlayAvailable`, `overlayReason`, `freshness`, and `ageMs` across Quest and Desktop surfaces.
- Tighten latest-frame-wins plus stale-hold interpretation so old, empty, or expired overlay results are never misread as fresh failures.

## Files to Modify

- `Gateway/main.py`
- `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs`
- `Assets/Scripts/BYES/Quest/ByesQuest3SelfTestRunner.cs`
- `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`
- `Assets/Scripts/BYES/Quest/ByesVisionHudController.cs`
- `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs`
- `VERSION`
- `docs/English/RELEASE_NOTES.md`
- `docs/Chinese/RELEASE_NOTES.md`
- `docs/maintainer/ACTIVE_PLAN.md`
- `docs/maintainer/REPO_FACTS.json`

## Files or Modules Explicitly Not Touched

- `Gateway/contracts/**`
- `Gateway/services/inference_service/providers/**`
- `Gateway/byes/recording/**`
- `Gateway/scripts/replay_run_package.py`
- `Gateway/scripts/report_run.py`
- `Gateway/scripts/run_regression_suite.py`
- `Gateway/services/pyslam_service/**`
- `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs`
- `Assets/Scripts/BYES/Quest/ByesVoiceCommandRouter.cs`
- `Assets/BeYourEyes/Presenters/Audio/**`
- `Assets/Scripts/BYES/Quest/ByesPassthroughController.cs`
- `Assets/Scenes/Quest3SmokeScene.unity`
- `Assets/Prefabs/BYES/Quest/BYES_HandMenu.prefab`
- `Assets/Prefabs/BYES/Quest/BYES_WristMenu.prefab`

## Quest Manual Acceptance Steps

1. Launch the realstack flow and confirm Desktop Console `/ui` is reachable.
2. Post one or more frames through `/api/frame` with `seg` and `depth` enabled.
3. Confirm `/api/providers` reports `seg.truthState=real` and `depth.truthState=real`, with concrete `device` and `deviceReason`.
4. Confirm `/api/ui/state.latest.overlayAssets.depth.assetId` is populated and carries `overlayAvailable=true`, `freshness`, and `ageMs`.
5. If the current frame yields no segmentation mask, confirm `/api/ui/state.latest.overlayAssets.seg` reports `truthState=real`, `overlayAvailable=false`, and `overlayReason=no_segments`.
6. Confirm Desktop Console shows depth preview as the primary visible overlay and does not treat `seg=no_segments` as an unavailable provider.
7. In Quest, confirm the panel text includes `latestOverlayKind`, freshness, age, device/deviceReason, and does not imply a broken pipeline when segmentation returns `no_segments`.
8. Run SelfTest and confirm the summary reports `overlay:seg=skip(no_segments)` when that exact case occurs, while depth still requires a visible overlay to pass.

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

- Main risk: stale-hold can look healthy while actually showing an old asset; freshness and age must remain visible on both Desktop and Quest.
- Secondary risk: broadening the `seg=no_segments` exemption would hide real overlay faults, so only that exact reason may skip failure.
- Rollback rule: keep `v5.09.1` provider truth and overlay loop as the baseline; revert only the stabilization-layer state mapping and SelfTest semantic change if smoke behavior regresses.
- First rollback targets if the smoke chain regresses: `Assets/Scripts/BYES/Quest/ByesQuest3SelfTestRunner.cs`, `Gateway/main.py`, `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs`, and `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`.
