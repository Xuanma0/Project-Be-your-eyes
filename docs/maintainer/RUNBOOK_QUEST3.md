# RUNBOOK_QUEST3

> Goal: Quest 3 local loop: passthrough visible -> controller scan upload -> Gateway WS event -> TTS feedback, with optional Live Loop (continuous frames) under backpressure.

## 1) Build Prerequisites

- Unity version: `6000.3.5f2` (`ProjectSettings/ProjectVersion.txt`).
- XR packages present:
  - `com.unity.xr.openxr`
  - `com.unity.xr.meta-openxr` (>= 2.3.0 in this repo)
  - `com.unity.xr.arfoundation`
  - Evidence: `Packages/manifest.json`.
- Build scenes:
  - `Assets/Scenes/SampleScene.unity` (existing)
  - `Assets/Scenes/Quest3SmokeScene.unity` (added for Quest smoke)
  - Evidence: `ProjectSettings/EditorBuildSettings.asset`.

## 2) Passthrough Requirements

- Camera clear flags must be solid color with alpha `A=0`.
- AR session + AR camera manager/background must exist at runtime.
- Runtime helper script enforces this in `Quest3SmokeScene`:
  - `Assets/Scripts/BYES/UI/ByesQuestPassthroughSetup.cs`.

## 3) LAN Setup (PC + Quest)

1. Ensure PC and Quest are on the same LAN / Wi-Fi.
2. Start Gateway with LAN bind:
```bash
python -m uvicorn main:app --app-dir Gateway --host 0.0.0.0 --port 8000
```
3. Note the PC LAN IP (example: `192.168.1.20`).
4. If API key guard is enabled, keep the same key for Unity panel:
   - `BYES_GATEWAY_API_KEY=YOUR_KEY_HERE`.
5. Optional version/build visibility in panel:
   - `BYES_GIT_SHA=<commit_sha>`
   - `BYES_VERSION_OVERRIDE=vX.YY` (only if you need temporary override for test environments).

## 4) Run Steps

1. Build and run `Quest3SmokeScene` on Quest 3.
2. Open runtime connection panel (`ByesConnectionPanel` auto-installs on this scene).
3. Set host/IP to PC LAN IP, port `8000`, optional API key, then click `Save + Connect`.
4. Click `Test Ping` and verify RTT appears.
5. Click `Read Mode` and verify mode value from Gateway.
6. Click `Get Version` and verify `version/gitSha` from Gateway.
7. Trigger manual scan with right-hand trigger (desktop fallback is `S`).
8. Toggle Live Loop:
   - Quest: right-hand primary button (A)
   - Desktop: `L`
9. Keep `liveMaxInflight=1` (default) to avoid request pile-up.
10. Verify loop:
   - Gateway receives `/api/frame`
   - Unity receives `/ws/events`
   - Speech output is heard.

## 小白两步法（USB/局域网）

### USB two-step (recommended for first smoke)

1. On PC:
```powershell
powershell -ExecutionPolicy Bypass -File tools/quest3/quest3_smoke.ps1 --usb
```
2. Put on Quest and open app:
   - Keep host as `127.0.0.1` in panel (USB reverse tunnel).
   - Wait for startup self-test status to become `PASS`.

### LAN two-step

1. On PC:
```powershell
powershell -ExecutionPolicy Bypass -File tools/quest3/quest3_smoke.ps1 --lan --gatewayHost 0.0.0.0
```
2. On Quest panel:
   - Set host to your PC LAN IP (script prints IPv4 candidates), then `Save + Connect`.
   - Wait for startup self-test `PASS`.

## 5) Runtime Controls

- Mode buttons in panel:
  - `Walk`, `Read`, `Inspect`
- These call existing mode chain:
  - `ByesModeManager.SetMode(...)` -> `GatewayClient.PostModeChange(...)` -> `POST /api/mode`.
- Live loop controls (`ScanController`):
  - `liveEnabledDefault` (default `false`)
  - `liveFps` (default `2.0`)
  - `liveMaxInflight` (default `1`)
  - `liveDropIfBusy` (default `true`)

## 6) Recommended Capture Settings (Quest 3)

- `ScreenFrameGrabber` defaults tuned for LAN stability:
  - `maxWidth=960`
  - `maxHeight=540`
  - `jpegQuality=70`
  - `keepAspect=true`
- If network/CPU headroom is limited, lower to `720x405` and quality `60`.
- If quality is insufficient, raise gradually and watch panel `Last Upload Cost` + `Last E2E`.

## 7) Measurement Template (copy/paste)

```text
Date:
Gateway VERSION:
Gateway gitSha:
Network:
Quest Scene:
Live Enabled:
liveFps:
liveMaxInflight:
Capture maxWidth/maxHeight/jpegQuality:
Ping RTT (median/p95):
Last Upload Cost (median/p95):
Last E2E (median/p95):
Dropped frame behavior observed (yes/no):
Notes:
```

## 8) Troubleshooting

- Black passthrough:
  - Check camera alpha is 0 and AR session/camera manager are active.
  - Confirm `ByesQuestPassthroughSetup` exists in runtime hierarchy.
- WS never connects:
  - Confirm host/IP is PC LAN IP (not `127.0.0.1`).
  - Confirm firewall allows inbound `8000`.
  - If API key enabled, ensure key matches.
- Ping fails:
  - Verify `POST /api/ping` reachable from Quest.
  - Check `X-BYES-API-Key` when guard enabled.
- Scan button does nothing:
  - Confirm `ScanController` is present and gateway connection is up.
  - Check controller input mapping / right-hand trigger (manual) and primary button (live toggle).
- Live mode causes rising latency:
  - Confirm `liveMaxInflight=1` and `liveDropIfBusy=true`.
  - Lower `liveFps` and/or capture size/quality.
- No audio/TTS:
  - Confirm WS events are arriving and `SpeechOrchestrator` is active.
- Unity compile shows `CS0246 ... BYES` under `Assets/BeYourEyes/**`:
  - Run `python tools/check_unity_layering.py`.
  - This indicates a layering regression (`BeYourEyes` should not compile-reference `BYES` namespace).
- Runtime throws `InvalidOperationException` about `UnityEngine.Input` while Input System package is active:
  - Run `python tools/check_unity_legacy_input.py`.
  - Move any `Input.GetKey*` call behind `#if ENABLE_LEGACY_INPUT_MANAGER`.
