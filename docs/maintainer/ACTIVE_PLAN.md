# ACTIVE_PLAN

Canonical active execution plan.
- Source: approved narrow `v5.08.4 Real SEG/DEPTH Activation` scope from maintainer discussion on `2026-03-08`.
- Updated: `2026-03-08`.
- Scope: current approved version plan until superseded by a newer maintainer decision.

## Current Version Goal

- Replace the `sam3` segmentation-service stub with real inference while keeping the existing `/seg` contract and existing `seg.mask.v1` asset flow.
- Replace the `da3` depth-service stub with real inference while keeping the existing `/depth` contract and existing `depth.map.v1` asset flow.
- Once real inference succeeds, make `seg` and `depth` truth resolve to `real` in `/api/providers`, `/api/capabilities`, `/api/ui/state`, Desktop Console, and Quest-facing provider summaries.
- Ensure a normal `/api/frame` run updates `latest.overlayAssets.seg.assetId` and `latest.overlayAssets.depth.assetId`, so Desktop preview and Quest whole-FOV HUD receive real overlay assets instead of staying unavailable.

## Files to Modify

- `Gateway/services/sam3_seg_service/app.py`
- `Gateway/services/da3_depth_service/app.py`
- `Gateway/main.py`
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
- `Gateway/scripts/pyslam_run_package.py`
- `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs`
- `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`
- `Assets/Scripts/BYES/Quest/ByesVisionHudController.cs`
- `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs`
- `Assets/Scenes/Quest3SmokeScene.unity`
- `Assets/Prefabs/BYES/Quest/BYES_HandMenu.prefab`
- `Assets/Prefabs/BYES/Quest/BYES_WristMenu.prefab`

## Quest Manual Acceptance Steps

1. Run `tools\\quest3\\quest3_usb_realstack_v5_08_2.cmd --preflight-only` and confirm `SEG` and `DEPTH` print `READY_REAL`.
2. Launch the realstack flow and confirm Desktop Console `/ui` is reachable.
3. Post one frame through `/api/frame` with `seg` and `depth` enabled.
4. Confirm `/api/providers` reports `seg.truthState=real` and `depth.truthState=real`.
5. Confirm `/api/ui/state.latest.overlayAssets.seg.assetId` and `.depth.assetId` are both populated.
6. Confirm Desktop Console preview tiles no longer show `SEG` or `DEPTH` as unavailable.
7. In Quest, confirm provider summary changes to `SEG=real` and `DEPTH=real`.
8. Confirm Quest whole-FOV HUD shows at least one valid `seg` or `depth` overlay layer.

## Required Gates

```bash
python tools/check_docs_links.py
python tools/check_unity_meta.py
cd Gateway && python -m pytest -q -n auto --dist loadgroup
cmd /c tools\unity\build_quest3_android.cmd
```

## Main Risks and Rollback Plan

- Main risk: service-level real inference works, but Gateway still times out on CPU and leaves `seg` or `depth` stuck at `unavailable(timeout)` despite correct local model wiring.
- Secondary risk: real responses break the existing event or asset path if `segments` or `grid` payloads drift from current normalization expectations.
- Rollback rule: preserve the current `/seg` and `/depth` payload shapes and fall back only to provider-truth or timeout adjustments; do not change contracts or Quest UI structure.
- First rollback targets if the smoke chain regresses: `Gateway/main.py`, `Gateway/services/sam3_seg_service/app.py`, and `Gateway/services/da3_depth_service/app.py`.
