> Compatibility note: this versioned file is kept for one-version compatibility.
> Default fact source: `docs/maintainer/CODEX_HANDOFF.md`.
> Historical archive: `docs/maintainer/archive/CODEX_HANDOFF_v5.04.md`.

# CODEX_HANDOFF_v5.04

Read `docs/maintainer/ARCHITECTURE_REVIEW.md` before implementing vNext.

Snapshot:
- Branch: `feature/unity-skeleton`
- HEAD: `86ba11fba56d52cfc6c1f4c54520dbd99cdc0fac`
- `VERSION`: `v5.05`
- Filename note: handoff file keeps `v5.04` label by maintainer request, but repo runtime version is already `v5.05`

## Current HEAD / VERSION

- Unity editor target: `6000.3.10f1`
- Enabled build scene: `Assets/Scenes/Quest3SmokeScene.unity`
- Preferred Quest launcher: `tools/quest3/quest3_usb_realstack_v5_05.cmd`

## This branch's invariants

- Do not casually change `Assets/Editor/ByesQuest3SmokeSceneInstaller.cs`; it enforces the Quest smoke scene object graph and build scene.
- Do not remove `/api/assets/*`, `/api/ui/state`, or `/ui` unless you replace both Quest HUD and desktop-console consumers.
- Do not claim `PCA` is real capture integration; current `ByesPcaFrameSource` is an AR CPU image fallback and reports `pcaAvailable=false`.
- Keep `frame.input`, `frame.ack`, `det.objects.v1`, `seg.mask.v1`, `depth.map.v1`, `vis.overlay.v1`, `target.session`, `target.update` contract-compatible.
- Do not bypass `Gateway/contracts/contract.lock.json`; update contracts deliberately and run the lock gate.
- Treat Quest local TTS as client-side truth. Gateway only records TTS runtime evidence from `frame.ack`.

## Known fragile files

- `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`
- `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs`
- `Assets/Scripts/BYES/Quest/ByesVisionHudController.cs`
- `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs`
- `Assets/Editor/ByesQuest3SmokeSceneInstaller.cs`
- `Gateway/main.py`
- `Gateway/services/inference_service/app.py`
- `tools/quest3/quest3_usb_realstack_v5_05.cmd`

## How to tell real vs mock quickly

- Check `GET /api/capabilities` and `GET /api/providers` first.
- Open `http://127.0.0.1:18000/ui` when using the realstack launcher.
- In Quest, read provider summary plus HUD output together. Panel-only updates are not enough.
- If `frameSource=pca` but `frameSourceMode=ar_cpuimage_fallback` and `pcaAvailable=false`, it is fallback, not real PCA.
- `DET/SEG/DEPTH` are "real enough" only when Quest HUD actually shows overlay assets, not just panel timestamps.
- `ASR` is real only when backend reports `faster_whisper`; repo default is mock/disabled.
- `TTS` is real on Quest whenever Android TTS speaks and `frame.ack` carries TTS evidence.
- `pySLAM realtime` is not a safe assumption; offline run-package pySLAM is the more credible path.

## Required gates before pushing

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

## Before vNext

Before implementing `vNext`, read `ARCHITECTURE_REVIEW.md` first.
