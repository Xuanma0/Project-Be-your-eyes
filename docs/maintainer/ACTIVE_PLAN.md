# ACTIVE_PLAN

Canonical active execution plan.
- Source: approved `v5.09 Real Overlay Loop & GPU Bring-up` scope from maintainer discussion on `2026-03-08`.
- Updated: `2026-03-08`.
- Scope: current approved version plan until superseded by a newer maintainer decision.

## Current Version Goal

- Keep `sam3` and `da3` on the existing real `/seg` and `/depth` paths, but move them from single-shot activation into a stable overlay loop with latest-frame-wins semantics.
- Probe `cuda` on startup with a real warmup infer; only surface `device=cuda` after warmup succeeds, otherwise fall back to `cpu` immediately and preserve a visible `deviceReason`.
- Keep Gateway as the only provider-truth source, and make `Quest HUD / Quest Panel / Desktop Console / /api/providers / /api/capabilities / /api/ui/state` agree on `backend`, `model`, `device`, `deviceReason`, `lastInferMs`, and overlay freshness for `seg` / `depth`.
- Preserve last-frame-hold behavior on Quest while preventing old `seg` / `depth` overlay results from overwriting newer frames.

## Files to Modify

- `Gateway/services/sam3_seg_service/app.py`
- `Gateway/services/da3_depth_service/app.py`
- `Gateway/main.py`
- `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs`
- `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`
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
- `Assets/Scripts/BYES/Quest/ByesVisionHudController.cs`
- `Assets/Scenes/Quest3SmokeScene.unity`
- `Assets/Prefabs/BYES/Quest/BYES_HandMenu.prefab`
- `Assets/Prefabs/BYES/Quest/BYES_WristMenu.prefab`

## Quest Manual Acceptance Steps

1. Launch the realstack flow and confirm Desktop Console `/ui` is reachable.
2. Confirm `sam3` and `da3` health endpoints show a final `actualDevice` plus `deviceReason`, with `cuda` only when warmup really succeeded.
3. Post one or more frames through `/api/frame` with `seg` and `depth` enabled.
4. Confirm `/api/providers` reports `seg.truthState` and `depth.truthState` from real runtime evidence instead of `not_started`, while also exposing `device` and `deviceReason`.
5. Confirm `/api/ui/state.latest.overlayAssets.depth.assetId` is populated and carries `freshness`, `ageMs`, `device`, and `deviceReason`; `seg` may remain asset-missing if the real model returns `no_segments`, but its provider truth must still update from runtime evidence.
6. Confirm Desktop Console preview tiles show a real depth overlay, and do not show stale or unavailable state for a newer frame once a newer asset id arrives.
7. In Quest, confirm provider summary changes to `SEG=real` and `DEPTH=real` and the panel text includes device / infer / overlay freshness evidence.
8. Confirm Quest whole-FOV HUD shows at least one valid `seg` or `depth` overlay layer while older overlays do not overwrite newer frames.

## Required Gates

```bash
python tools/check_docs_links.py
python tools/check_unity_meta.py
python tools/check_unity_layering.py
python tools/check_unity_legacy_input.py
cd Gateway && python -m pytest -q -n auto --dist loadgroup
cmd /c tools\unity\build_quest3_android.cmd
```

## Main Risks and Rollback Plan

- Main risk: `cuda` probing half-succeeds and leaves provider truth claiming GPU while the runtime actually fell back or timed out.
- Secondary risk: slow `seg` inference causes old overlay results to arrive after newer frames unless both Gateway and Quest continue to drop stale frame ids.
- Rollback rule: keep the real CPU path from `v5.08.4` as the baseline and only revert the new `deviceReason` / latest-frame-wins glue if the smoke chain regresses; do not change contracts or menu IA.
- First rollback targets if the smoke chain regresses: `Gateway/services/sam3_seg_service/app.py`, `Gateway/services/da3_depth_service/app.py`, `Gateway/main.py`, and `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs`.
