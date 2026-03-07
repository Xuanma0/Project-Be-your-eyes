# CODEX_HANDOFF

Canonical maintainer handoff.
- Source: reorganized from `docs/maintainer/CODEX_HANDOFF_v5.04.md`, `docs/maintainer/ARCHITECTURE_REVIEW_v5.04.md`, and `docs/maintainer/REPO_FACTS_v5.04.json`.
- Updated: `2026-03-07`.
- Historical snapshot: `docs/maintainer/archive/CODEX_HANDOFF_v5.04.md`.

## Read First

For every new session, read in this order:

1. `docs/maintainer/ARCHITECTURE_REVIEW.md`
2. `docs/maintainer/CODEX_HANDOFF.md`
3. `docs/maintainer/REPO_FACTS.json`
4. `docs/maintainer/ACTIVE_PLAN.md`

Then read the relevant file under `docs/codex/` for the active version only.

## Current HEAD / VERSION

- Branch: `feature/unity-skeleton`
- HEAD: `86ba11fba56d52cfc6c1f4c54520dbd99cdc0fac`
- `VERSION`: `v5.05`
- Unity editor target: `6000.3.10f1`
- Enabled build scene: `Assets/Scenes/Quest3SmokeScene.unity`
- Preferred Quest launcher: `tools/quest3/quest3_usb_realstack_v5_05.cmd`

## This Branch's Invariants

- Do not casually change `Assets/Editor/ByesQuest3SmokeSceneInstaller.cs`; it enforces the Quest smoke scene object graph and build scene.
- Do not remove `/api/assets/*`, `/api/ui/state`, or `/ui` unless you replace both Quest HUD and desktop-console consumers.
- Do not claim `PCA` is real capture integration; current `ByesPcaFrameSource` is an AR CPU image fallback and reports `pcaAvailable=false`.
- Keep `frame.input`, `frame.ack`, `det.objects.v1`, `seg.mask.v1`, `depth.map.v1`, `vis.overlay.v1`, `target.session`, and `target.update` contract-compatible.
- Do not bypass `Gateway/contracts/contract.lock.json`; update contracts deliberately and run the lock gate.
- Treat Quest local TTS as client-side truth. Gateway only records TTS runtime evidence from `frame.ack`.

## Known Fragile Files

- `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`
- `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs`
- `Assets/Scripts/BYES/Quest/ByesVisionHudController.cs`
- `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs`
- `Assets/Editor/ByesQuest3SmokeSceneInstaller.cs`
- `Gateway/main.py`
- `Gateway/services/inference_service/app.py`
- `tools/quest3/quest3_usb_realstack_v5_05.cmd`

## How to Tell Real vs Mock Quickly

- Check `GET /api/capabilities` and `GET /api/providers` first.
- Open `http://127.0.0.1:18000/ui` when using the realstack launcher.
- In Quest, read provider summary plus HUD output together. Panel-only updates are not enough.
- If `frameSource=pca` but `frameSourceMode=ar_cpuimage_fallback` and `pcaAvailable=false`, it is fallback, not real PCA.
- `DET/SEG/DEPTH` are only "real enough" when Quest HUD actually shows overlay assets, not just panel timestamps.
- `ASR` is real only when backend reports `faster_whisper`; repo default is mock or disabled.
- `TTS` is real on Quest whenever Android TTS speaks and `frame.ack` carries TTS evidence.
- `pySLAM realtime` is not a safe assumption; offline run-package pySLAM is the more credible path.

## Required Gates Before Pushing

```bash
python Gateway/scripts/verify_contracts.py --check-lock
python Gateway/scripts/run_regression_suite.py --suite Gateway/regression/suites/baseline_suite.json --baseline Gateway/regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
python Gateway/scripts/run_regression_suite.py --suite Gateway/regression/suites/contract_suite.json --baseline Gateway/regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
python Gateway/scripts/lint_run_package.py --run-package Gateway/tests/fixtures/run_package_with_events_v1_min
python tools/check_unity_meta.py
python tools/check_docs_links.py
```

If you touched Quest realtime flow, also run:

```bat
tools\quest3\quest3_usb_realstack_v5_05.cmd
```

and confirm:
- `HTTP reachable`
- `WS connected`
- at least one HUD overlay is visible
- `SelfTest` does not regress

## Before Implementing vNext

Before implementing `vNext`, read `docs/maintainer/ARCHITECTURE_REVIEW.md` first, then `docs/maintainer/ACTIVE_PLAN.md`, then the relevant file under `docs/codex/`.
