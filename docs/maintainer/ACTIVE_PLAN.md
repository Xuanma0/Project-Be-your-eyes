# ACTIVE_PLAN

Canonical active execution plan.
- Source: approved `v5.09.1 Blackwell CUDA bring-up + overlay usability` scope from maintainer discussion on `2026-03-09`.
- Updated: `2026-03-09`.
- Scope: current approved version plan until superseded by a newer maintainer decision.

## Current Version Goal

- Keep the existing CPU real path intact while probing an optional `BYES_PYTHON_EXE_CUDA128` environment for `sam3` and `da3`; only a successful warmup may surface `device=cuda`.
- Preserve honest fallback: if CUDA warmup fails at probe time or at live service startup, the service must run on `cpu` and expose a concrete `deviceReason` instead of pretending GPU is active.
- Improve whole-FOV overlay usability without adding new UI IA: make depth the default most-visible layer, keep last-frame-hold, and surface overlay kind/freshness/age/device evidence in the Quest panel and Desktop Console.
- Keep Gateway as the only provider-truth source, and make `Quest HUD / Quest Panel / Desktop Console / /api/providers / /api/capabilities / /api/ui/state` agree on `backend`, `model`, `device`, `deviceReason`, `truthState`, and latest overlay asset evidence for `seg` / `depth`.

## Files to Modify

- `Gateway/services/sam3_seg_service/app.py`
- `Gateway/services/da3_depth_service/app.py`
- `Gateway/main.py`
- `Assets/Scripts/BYES/Quest/ByesVisionHudController.cs`
- `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs`
- `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`
- `tools/quest3/quest3_usb_realstack_v5_08_2.cmd`
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
- `Assets/Scenes/Quest3SmokeScene.unity`
- `Assets/Prefabs/BYES/Quest/BYES_HandMenu.prefab`
- `Assets/Prefabs/BYES/Quest/BYES_WristMenu.prefab`

## Quest Manual Acceptance Steps

1. Launch the realstack flow and confirm Desktop Console `/ui` is reachable.
2. Confirm `sam3` and `da3` health endpoints show a final `actualDevice` plus `deviceReason`, with `cuda` only after a successful warmup infer and `cpu` plus reason on fallback.
3. Post one or more frames through `/api/frame` with `seg` and `depth` enabled.
4. Confirm `/api/providers` reports `seg.truthState` and `depth.truthState` from real runtime evidence and surfaces final `backend`, `model`, `device`, and `deviceReason` instead of wrapper-only metadata.
5. Confirm `/api/ui/state.latest.overlayAssets.depth.assetId` is populated and carries `freshness`, `ageMs`, `device`, and `deviceReason`; `seg` may stay asset-missing when the real model returns `no_segments`, but the reason must be visible rather than looking like an overlay failure.
6. Confirm Desktop Console shows at least one live previewable overlay layer, with depth preferred as the default clearly visible whole-FOV layer.
7. In Quest, confirm provider summary changes to `SEG=real` and `DEPTH=real` and the panel text includes overlay kind / infer / freshness / device evidence.
8. Confirm Quest whole-FOV HUD holds the last successful overlay and does not reapply older results over a newer frame.

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

- Main risk: Blackwell `cu128` probing succeeds in isolation but `sam3` still falls back under real co-resident memory pressure; truth must follow the live runtime, not the optimistic probe.
- Secondary risk: improving overlay visibility could regress into stale-hold looking “alive” while actually showing an old asset; freshness and age must remain visible.
- Rollback rule: keep the CPU real path from `v5.09` as the baseline and only revert the new cu128 probe glue plus overlay-visibility tuning if the smoke chain regresses; do not change contracts or menu IA.
- First rollback targets if the smoke chain regresses: `tools/quest3/quest3_usb_realstack_v5_08_2.cmd`, `Gateway/services/sam3_seg_service/app.py`, `Gateway/services/da3_depth_service/app.py`, `Gateway/main.py`, and `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs`.
