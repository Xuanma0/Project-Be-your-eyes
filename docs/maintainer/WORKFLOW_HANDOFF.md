# WORKFLOW_HANDOFF

Canonical development-workflow handoff.
- Source: reorganized from `docs/maintainer/WORKFLOW_HANDOFF_v5.04.md`, `docs/maintainer/ARCHITECTURE_REVIEW_v5.04.md`, and `docs/maintainer/REPO_FACTS_v5.04.json`.
- Updated: `2026-03-08`.
- Historical snapshot: `docs/maintainer/archive/WORKFLOW_HANDOFF_v5.04.md`.

## Read First

For every new session, read in this order:

1. `docs/maintainer/ARCHITECTURE_REVIEW.md`
2. `docs/maintainer/WORKFLOW_HANDOFF.md`
3. `docs/maintainer/REPO_FACTS.json`
4. `docs/maintainer/ACTIVE_PLAN.md`
5. `docs/maintainer/DECISIONS.md`

If a version-specific execution brief exists, treat it as an external temporary working note rather than repository memory.

## Current HEAD / VERSION

- Branch: `feature/unity-skeleton`
- HEAD: release commit for `v5.08.1` hotfix; use `git rev-parse HEAD` for the exact current value.
- `VERSION`: `v5.08.1`
- Unity editor target: `6000.3.10f1`
- Enabled build scene: `Assets/Scenes/Quest3SmokeScene.unity`
- Preferred Quest launcher: `tools/quest3/quest3_usb_realstack_v5_08.cmd`

## This Branch's Invariants

- Do not casually change `Assets/Editor/ByesQuest3SmokeSceneInstaller.cs`; it enforces the Quest smoke scene object graph and build scene.
- Do not remove `/api/assets/*`, `/api/ui/state`, or `/ui` unless you replace both Quest HUD and desktop-console consumers.
- Do not claim `PCA` is real capture integration unless capture truth is actually `pca_real`; current fallback path must report `ar_cpuimage_fallback`, `rendertexture_fallback`, or `unavailable`.
- `pca_real` requires supported Quest 3 or 3S hardware, non-Link runtime, camera permission, provider availability, and provider readiness at the same time.
- Keep `frame.input`, `frame.ack`, `det.objects.v1`, `seg.mask.v1`, `depth.map.v1`, `vis.overlay.v1`, `target.session`, and `target.update` contract-compatible.
- Do not bypass `Gateway/contracts/contract.lock.json`; update contracts deliberately and run the lock gate.
- Treat Quest local TTS as client-side truth. Gateway only records TTS runtime evidence from `frame.ack`.
- Keep ASR and TTS evidence separate: ASR truth comes from Gateway recognition runtime; TTS truth comes from Quest-local playback runtime.
- Keep `pySLAM` optional. It may be visible in diagnostics, but it is not part of the default smoke success criteria.
- Keep Desktop Console as a thin wrapper on existing APIs. Add controls there only when they map directly to existing `/api/frame`, `/api/assist`, `/api/record/*`, `/api/mode`, `/api/capabilities`, `/api/providers`, or `/api/ui/state` flows.
- In the `v5.08.1` hotfix band, prioritize truth stabilization over new features: provider evidence, overlay asset lifecycle, passthrough fallback honesty, and hand-menu usability outrank new capability work.

## Known Fragile Files

- `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`
- `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs`
- `Assets/Scripts/BYES/Quest/ByesVisionHudController.cs`
- `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs`
- `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs`
- `Assets/Editor/ByesQuest3SmokeSceneInstaller.cs`
- `Gateway/main.py`
- `Gateway/services/inference_service/app.py`
- `tools/quest3/quest3_usb_realstack_v5_08.cmd`

## How to Tell Real vs Mock Quickly

- Check `GET /api/capabilities` and `GET /api/providers` first.
- Open `http://127.0.0.1:18000/ui` when using the realstack launcher.
- In Quest, read provider summary plus HUD output together. Panel-only updates are not enough.
- If frame source is anything other than `pca_real`, it is not true capture.
- `DET/SEG/DEPTH` are only "real enough" when Quest HUD actually shows overlay assets, not just panel timestamps.
- `ASR` is real only when backend reports `faster_whisper`; repo default is mock or disabled.
- `TTS` is real on Quest whenever Android TTS speaks and `frame.ack` carries TTS evidence; muted Quest TTS must surface as `muted`, not `real`.
- `pySLAM realtime` is not a safe assumption; offline run-package pySLAM is the more credible path.

## Required Gates Before Pushing

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

If you touched Quest realtime flow, also run:

```bat
tools\quest3\quest3_usb_realstack_v5_08.cmd
```

and confirm:
- `HTTP reachable`
- `WS connected`
- at least one HUD overlay is visible
- `SelfTest` does not regress

## Before Implementing vNext

Before implementing `vNext`, read `docs/maintainer/ARCHITECTURE_REVIEW.md`, `docs/maintainer/WORKFLOW_HANDOFF.md`, `docs/maintainer/REPO_FACTS.json`, `docs/maintainer/ACTIVE_PLAN.md`, and `docs/maintainer/DECISIONS.md` in that order.
