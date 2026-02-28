# RUNBOOK_QUEST3

> Goal: Quest 3 local loop: passthrough visible -> scan upload -> Gateway WS event -> TTS feedback, with optional Live Loop under backpressure.

## 1) Build Prerequisites

- Unity version: `6000.3.5f2` (`ProjectSettings/ProjectVersion.txt`).
- XR packages present:
  - `com.unity.xr.openxr`
  - `com.unity.xr.meta-openxr` (>= 2.3.0)
  - `com.unity.xr.arfoundation`
- Build scenes:
  - `Assets/Scenes/Quest3SmokeScene.unity`
  - `Assets/Scenes/SampleScene.unity`

## 2) Passthrough Requirements

- Camera clear flags: solid color and alpha `A=0`.
- AR session + AR camera manager/background must exist at runtime.
- Runtime helper script:
  - `Assets/Scripts/BYES/UI/ByesQuestPassthroughSetup.cs`

## 3) USB Mode (Recommended in CN)

This avoids LAN/firewall instability and is the recommended first run.

1. On PC:
```bat
tools\quest3\quest3_usb_local_gateway.cmd
```
2. On Quest connection panel:
   - `host = 127.0.0.1`
   - `port = 18000`
3. Click `Save + Connect` -> `Test Ping` -> `Get Version`.

Notes:
- Script uses `adb reverse tcp:18000 tcp:18000`.
- If adb path is custom, set env `ADB_EXE` before running.

## 4) LAN Mode (Alternative)

1. Ensure PC and Quest are on same LAN / Wi-Fi.
2. Start Gateway bind to LAN:
```bash
python -m uvicorn main:app --app-dir Gateway --host 0.0.0.0 --port 8000
```
3. In panel, use PC LAN IP and port `8000`.

## 5) WinError 10013 Mitigation

If port `8000` is blocked by local policy (`WinError 10013`), switch to `18000`.

- Gateway:
```bash
python Gateway/scripts/dev_up.py --gateway-only --host 127.0.0.1 --gateway-port 18000 --no-reload
```
- Quest panel:
  - USB mode: `host=127.0.0.1`, `port=18000`
  - LAN mode: `host=<PC LAN IP>`, `port=18000`

## 6) 如果你只看到 MODE:WALK 但没有面板

1. Verify project version is `v4.96` or newer.
2. The auto-installed minimal panel defaults to `http://127.0.0.1:18000`.
3. Ensure adb reverse is active:
```bash
adb reverse tcp:18000 tcp:18000
# optional compatibility mapping
adb reverse tcp:8000 tcp:18000
```
4. Start Gateway on PC:
```bash
python -m uvicorn main:app --app-dir Gateway --host 127.0.0.1 --port 18000
```
5. In-headset panel buttons:
   - `Ping`: verifies `/api/ping`
   - `Version`: verifies `/api/version`
   - `Mode`: verifies `/api/mode`

## 7) Runtime Controls

- Manual scan: Quest right-hand trigger (desktop fallback `S`).
- Toggle live loop: Quest right-hand primary button/A (desktop fallback `L`).
- Mode switch: `Walk/Read/Inspect` panel buttons or `1/2/3` + `F1/F2/F3`.

## 8) Screenshot-Level Smoke Checklist

Use this checklist for team verification screenshots:

- `Ping OK`: RTT value is shown and updates.
- `Version OK`: `/api/version` returns non-empty version/gitSha.
- `WS Connected`: panel shows WS connected state.
- `Live Loop`: panel shows live `on`, fps and inflight values.
- `Frames Sent`: Gateway receives `/api/frame` while live loop runs.
- `Events Received`: panel/event line updates from `/ws/events`.

## 9) Recommended Capture Defaults

- `maxWidth=960`
- `maxHeight=540`
- `jpegQuality=70`
- `liveMaxInflight=1`
- `liveDropIfBusy=true`

## 10) Troubleshooting

- Black passthrough:
  - Check camera alpha = 0 and AR session/camera manager active.
- WS never connects:
  - Check host/port and firewall.
  - USB mode must run `adb reverse` first.
- Ping fails:
  - Verify `/api/ping` reachable and API key matches if enabled.
- Live latency keeps rising:
  - Keep `liveMaxInflight=1`, lower fps/quality/resolution.
- Unity compile `CS0246 ... BYES` under `Assets/BeYourEyes/**`:
  - Run `python tools/check_unity_layering.py`.
- Input runtime exceptions (`UnityEngine.Input` with Input System):
  - Run `python tools/check_unity_legacy_input.py`.
- Android batch build reports `build target unsupported`:
  - Install Unity Android Build Support (SDK/NDK/OpenJDK) for the selected editor.
  - Re-run `tools\\unity\\build_quest3_android.cmd`.
