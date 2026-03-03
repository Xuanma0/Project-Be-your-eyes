# RUNBOOK_QUEST3

> Goal: Quest 3 local loop: passthrough visible -> scan upload -> Gateway WS event -> TTS feedback, with optional Live Loop under backpressure.

## 1) Build Prerequisites

- Unity version: `6000.3.10f1` (`ProjectSettings/ProjectVersion.txt`).
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
   Real providers (OCR/DET/Depth) one-command launcher:
```bat
tools\quest3\quest3_usb_realstack_v5_01.cmd
```
   v5.02 pilot launcher (assist/find/record enabled):
```bat
tools\quest3\quest3_usb_realstack_v5_02.cmd
```
   v5.03 pilot launcher (assist/find/track/record + guidance toggles):
```bat
tools\quest3\quest3_usb_realstack_v5_03.cmd
```
   v5.04 pilot launcher (HUD overlays + asset endpoints + optional ASR/pySLAM realtime bridge):
```bat
tools\quest3\quest3_usb_realstack_v5_04.cmd
```
2. On Quest, open `Quest3SmokeScene` app and look at the floating panel in front of you.
3. Confirm panel base URL is `http://127.0.0.1:18000`.
4. Click `SelfTest` (single-button smoke). If status looks stale first, click `Refresh` once.

Notes:
- Script uses `adb reverse tcp:18000 tcp:18000`.
- Script starts Gateway with `BYES_INFERENCE_EMIT_WS_V1=1` and `BYES_EMIT_NET_DEBUG=1` for smoke observability.
- If adb path is custom, set env `ADB_EXE` before running.
- Real-stack script starts Gateway + inference_service and sets `BYES_SERVICE_OCR_PROVIDER=paddleocr`, `BYES_SERVICE_DET_PROVIDER=ultralytics`, `BYES_SERVICE_DEPTH_PROVIDER=onnx`.
- If optional dependencies or model path are missing, capabilities/selftest will show explicit failure reason instead of silent success.

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
5. In-headset panel:
   - Preferred: click `SelfTest` only.
   - Optional manual checks: `Ping` (`/api/ping`), `Version` (`/api/version`), mode buttons (`Walk/Read/Inspect` + `/api/mode`).

## 7) Runtime Controls

- Quest default (Android): use official palm-up hand menu (`Connection / Actions / Mode / Panels / Settings / Debug`).
- Manual scan: hand menu `Actions -> Scan Once` (desktop fallback key `S`).
- Toggle live loop: hand menu `Actions -> Live Toggle` (desktop fallback key `L`).
- Mode switch: hand menu `Mode -> Walk / Read / Inspect` or `Cycle`.
- Connection panel remains status-first; action buttons are hidden by default on Android.

## 7.1) Palm-up Menu + Safe Gestures (v5.00)

- Flip wrist (palm-up, facing yourself) reveals the hand menu automatically (default left hand), no extra pinch required.
- Gesture shortcuts (right hand):
  - thumb + middle pinch: `Scan Once`
  - thumb + ring pinch: `Live Toggle`
  - thumb + little pinch: `Cycle Mode`
- `Settings` group controls:
  - `Gesture Shortcuts` enable/disable
  - `Shortcut Hand`: RightOnly / LeftOnly / Both
  - `Conflict Mode`: Safe / Advanced
  - `Menu Hand`: Left / Right / Either
  - `Passthrough` toggle
- `Panels` group controls:
  - `Toggle Smoke Panel`
  - `LockToHead`
  - `Enable Move/Resize` (default OFF)
  - `Snap Default`
- Safe mode conflict isolation:
  - no shortcut triggers when hand menu is visible
  - no shortcut triggers during system gesture
  - no shortcut triggers while UI hover/select or panel grab is active

## 8) Scan Once / Live Smoke Flow (v4.97)

1. Confirm panel shows:
   - `HTTP: reachable`
   - `WS: connected`
2. Click `Scan Once` and wait 1-2 seconds.
3. Expected panel updates:
   - `Scan: uploaded` then `event_received` (or similar)
   - `Last Upload: <N> ms`
   - `Last Event: <event-type>`
   - `Last E2E: <N> ms` (coarse)
4. Click `Live Start` and observe updates for 10-15 seconds.
5. Click `Live Stop`.
6. Click `SelfTest`, expect `SelfTest: PASS`.

## 8.1) v5.01 Real OCR/DET/RISK Flow (USB)

1. Run `tools\quest3\quest3_usb_realstack_v5_01.cmd` on PC.
2. In Quest hand menu, run `SelfTest` and verify:
   - `Step3 /api/capabilities` returns provider info.
   - `depth+risk`, `ocr`, `det` steps all pass.
3. Manual action checks:
   - `Actions -> Read Text Once`: panel updates `Last OCR` and `Age`.
   - `Actions -> Detect Once`: panel updates `Last DET` and `Age`.
   - `Scan Once` or short `Live`: panel updates `Last RISK` and `Age`.
4. Toggle speech behavior in hand menu settings:
   - `Auto Speak OCR / DET / RISK`
   - `OCR Verbose`
5. Verify busy protection:
   - repeated identical OCR/risk text should not spam TTS within cooldown window.

## 8.2) v5.02 Find + Assist + Record Flow (USB)

1. Run:
```bat
tools\quest3\quest3_usb_realstack_v5_02.cmd
```
2. In Quest wrist menu:
   - `Actions -> Find Door` (or Exit/Stairs/Elevator/Restroom/Person)
   - Panel should update `Last FIND` and `Age`.
3. Verify assist path:
   - If cache is fresh, `/api/assist` is used (no extra frame upload required).
   - If cache miss occurs, client falls back to one-shot frame upload.
4. Record-and-replay loop:
   - `Actions -> Rec Start`
   - run a short flow (`Scan Once`, `Find`, optional `Live`)
   - `Actions -> Rec Stop`
5. Check PC terminal/log:
   - `/api/record/start` 200
   - `/api/record/stop` 200 and `recordingPath`
6. Replay generated package:
```bash
python Gateway/scripts/replay_run_package.py --run-package <recordingPath> --reset
python Gateway/scripts/report_run.py --run-package <recordingPath>
```

## 8.3) v5.03 ROI -> Target Tracking -> Guidance -> Recording (USB)

1. Start realstack:
```bat
tools\quest3\quest3_usb_realstack_v5_03.cmd
```
   Optional online pySLAM bridge:
```bat
set BYES_ENABLE_PYSLAM_SERVICE=1
tools\quest3\quest3_usb_realstack_v5_03.cmd
```
2. In Quest hand menu:
   - `Debug -> Run SelfTest` (PASS expected; passthrough may show `SKIP` with reason when unavailable).
3. Manual target-tracking loop:
   - `Actions -> Select ROI` (default center ROI is used in smoke profile)
   - `Actions -> Start Track`
   - `Actions -> Track Step` (repeat 2-5 times while moving view)
   - `Actions -> Stop Track`
4. Expected panel lines update:
   - `Last TARGET`
   - `Guidance` (`LEFT/RIGHT/CENTER/STOP`)
   - `Last Event` contains `target.session` / `target.update`
5. Guidance toggles:
   - `Settings -> Auto Guidance`
   - `Settings -> Guidance Audio`
   - `Settings -> Guidance Haptics` (controller-only; hand-tracking mode should not error when controller missing)
6. Recording loop:
   - `Actions -> Rec Start`
   - run short track/find/scan flow for 5-10s
   - `Actions -> Rec Stop`
   - verify PC terminal prints `recordingPath`

### Evidence checklist (v5.03)

- Quest screenshot with:
  - `HTTP: reachable`, `WS: connected`
  - `Last TARGET`, `Guidance`
  - `Last Upload`, `Last E2E`
- PC terminal snippets:
  - `/api/assist` with `target_start`/`target_step` returns 200
  - `/api/record/start` and `/api/record/stop` returns 200
  - printed `recordingPath`

## 8.4) Optional pySLAM Offline Runner

After record stop, you can post-process the run package with optional pySLAM:

```bash
python Gateway/scripts/pyslam_run_package.py --run-package <recordingPath> --pyslam-root <YOUR_PYSLAM_REPO_PATH>
```

- Output:
  - `out/pyslam/trajectory.json`
- If pySLAM root is missing, script exits with code `2` and prints setup guidance.

## 8.5) v5.04 Quest Validation (HUD + Voice + Optional pySLAM)

PC:
1. Run:
```bat
tools\quest3\quest3_usb_realstack_v5_04.cmd
```
2. Confirm launcher output includes:
   - `adb reverse tcp:18000 tcp:18000`
   - gateway/inference startup lines
   - optional pySLAM bridge enabled/disabled reason

Quest:
1. Open app, palm-up to show wrist menu, then check `Home` status: `HTTP reachable`, `WS connected`, `Record`, `Overlay`.
2. `Dev -> Run SelfTest` should PASS (or SKIP with explicit reason for optional capabilities like passthrough/ASR/pySLAM realtime).
3. `Vision` page:
   - enable DET/SEG/DEPTH/TARGET overlay
   - adjust SEG/DEPTH alpha
   - passthrough toggle + opacity + color/gray mode
4. Trigger `Read Text`, `Find`, and `Track` actions from `Home/Guidance/Dev`:
   - panel updates `Last OCR / Last FIND / Last TARGET`
   - HUD overlay updates age/fps stats
5. `Guidance` page:
   - set mode `Walk/Read/Inspect`
   - toggle auto guidance/audio/haptics and adjust guidance rate slider
6. `Voice` page:
   - `Play Beep` audible
   - `Speak Test` updates panel TTS status
   - if ASR enabled, `Push-to-talk` produces `asr.transcript.v1`
7. Favorites:
   - run any action, then `Dev -> Pin Last Action`
   - verify pinned action appears in `Home` favorites row and is clickable
8. Record checks:
   - `Start Record` -> operate 5-10s -> `Stop Record`
   - terminal prints `recordingPath`

Evidence checklist:
- Quest screenshot containing:
  - HTTP/WS
  - Last Upload/E2E
  - Last OCR/FIND/TARGET
  - Guidance + HUD stats
- PC logs containing:
  - `/api/assets/{asset_id}` GET lines
  - `seg.mask.v1` / `depth.map.v1` WS events
  - `/api/asr` request (when ASR enabled)
  - `/api/record/start` + `/api/record/stop` 200 lines

## 8.6) One-Command Auto Audit (v5.04)

When you want a repeatable PC-side check for `capabilities + record -> replay -> report`, run:

```bat
tools\quest3\quest3_auto_audit_v5_04.cmd
```

Optional args:

```bat
tools\quest3\quest3_auto_audit_v5_04.cmd http://127.0.0.1:18000 quest3-smoke 8
```

- arg1: base URL
- arg2: device id
- arg3: record duration seconds

Outputs are written to:

- `Gateway/artifacts/quest_audit/quest_v504_audit_summary.json`
- `Gateway/artifacts/quest_audit/quest_v504_audit_summary.md`
- `Gateway/artifacts/quest_audit/quest_v504_report.md`
- `Gateway/artifacts/quest_audit/quest_v504_report.json`

## 9) Diagnosing Periodic Hitch (v4.98)

When users report "every 1 second a brief freeze", check panel metrics with `Live OFF`:

1. Keep scene running for 30 seconds without touching buttons.
2. Watch panel lines:
   - `Hitch30s`
   - `WorstDt`
   - `GC0/1/2 Δ`
   - `CaptureHz ... Async: ON/OFF`
3. Expected for smoke baseline: `Hitch30s <= 1`.

Quick isolation:
- If `Live OFF` still hitches and `GC0 Δ` jumps, suspect UI/polling/alloc pressure.
- If hitch spikes happen during `Scan Once` with `Async: OFF`, enable async readback (`BYES_CAPTURE_USE_ASYNC_GPU_READBACK=1`).
- Use `Refresh` button for manual checks instead of frequent auto polling.

## 10) Screenshot-Level Smoke Checklist

Use this checklist for team verification screenshots:

- `Ping OK`: RTT value is shown and updates.
- `Version OK`: `/api/version` returns non-empty version/gitSha.
- `WS Connected`: panel shows WS connected state.
- `Scan Once OK`: `/api/frame` returns success and panel updates upload/event lines.
- `Live Loop`: panel shows live on/off and metrics update while running.
- `SelfTest PASS`: panel displays PASS with summary text.
- `Mode Switch`: click `Walk/Read/Inspect` and verify `Mode:` text changes accordingly.
- `Hitch Metric`: with live off for 30s, capture `Hitch30s` and `WorstDt` in screenshot.

## 10.1) No-Low-Buttons Smoke Flow (v5.00)

1. Start USB script: `tools\\quest3\\quest3_usb_local_gateway.cmd`.
2. Put on Quest and wait until panel shows `HTTP: reachable`.
3. Palm-up + pinch to open hand menu.
4. Click `Debug -> Run SelfTest` (or `Actions -> Scan Once` / `Live Toggle` manually).
5. Confirm panel updates: `WS connected`, `Last Upload`, `Last E2E`, `Last Event`.

## 10.2) Hand Menu Troubleshooting (v5.00)

- Menu mirrored/backward text:
  - re-run installer (`BYES/Quest3/Install Smoke Rig`) and ensure `BYES_HandMenuRoot/OfficialHandMenuRig` exists.
- Menu does not appear:
  - verify hand tracking is active and try palm-up + menu pinch gesture.
  - check `ByesXrUiWiringGuard` and `MetaSystemGestureDetector` are active in scene.
- Menu appears but cannot click:
  - ensure EventSystem uses `XRUIInputModule` only.
  - ensure menu canvas has `TrackedDeviceGraphicRaycaster`.
- Gesture shortcuts conflict:
  - set `Settings -> Conflict Mode -> Safe` and keep `Gesture Shortcuts` enabled.

## 11) Recommended Capture Defaults

- `maxWidth=960`
- `maxHeight=540`
- `jpegQuality=70`
- `liveMaxInflight=1`
- `liveDropIfBusy=true`
- `BYES_CAPTURE_USE_ASYNC_GPU_READBACK=1` (Quest recommended)
- `BYES_CAPTURE_TARGET_HZ=1` (smoke default)
- `BYES_CAPTURE_MAX_INFLIGHT=1`

## 11.1) Optional Real Provider Dependency Install

```bash
python -m pip install -r Gateway/services/inference_service/requirements-paddleocr.txt
python -m pip install -r Gateway/services/inference_service/requirements-ultralytics.txt
python -m pip install -r Gateway/services/inference_service/requirements-onnx-depth.txt
```

If depth provider is ONNX, set model path before running real-stack:

```bash
set BYES_SERVICE_DEPTH_ONNX_PATH=D:\models\depth_anything_v2_small.onnx
```

## 12) Troubleshooting

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
