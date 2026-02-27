# RUNBOOK_LOCAL

> Goal: reproducible local paths for offline evaluation and Unity realtime loop.

## Path A: Offline Evaluation (minimal)

### Prerequisites
1. Python 3.11 (`.github/workflows/gateway-ci.yml:25`).
2. Install deps:
```bash
python -m pip install --upgrade pip
python -m pip install -r Gateway/requirements.txt
```
Evidence: `.github/workflows/gateway-ci.yml:27-30`.

### Steps
1. Run tests (CI-equivalent):
```bash
cd Gateway
python -m pytest -q -n auto --dist loadgroup
```
Evidence: `.github/workflows/gateway-ci.yml:36`.
2. Replay one run package:
```bash
cd ..
python Gateway/scripts/replay_run_package.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min --reset
```
Optional hardened profile (Gateway key enabled):
```bash
python Gateway/scripts/replay_run_package.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min --reset --gateway-api-key YOUR_KEY_HERE
```
Evidence: `README.md` command + script entry `Gateway/scripts/replay_run_package.py:324`.
3. Generate report:
```bash
python Gateway/scripts/report_run.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min
```
Evidence: `README.md:57`; report generator `Gateway/scripts/report_run.py:905`.
4. Run regression gate:
```bash
python Gateway/scripts/run_regression_suite.py --suite Gateway/regression/suites/baseline_suite.json --baseline Gateway/regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
```
Evidence: `.github/workflows/gateway-ci.yml:44`.

### Success Signals
- `events/events_v1.jsonl` exists and is populated (replay normalization step, `Gateway/scripts/replay_run_package.py:402-403`).
- `report.json` and `report.md` generated in run package directory (`Gateway/scripts/report_run.py:905+`).
- Regression exits 0 and does not hit `missCriticalCount > 0` failure (`Gateway/scripts/run_regression_suite.py:1220`).

## Path B: Unity + Gateway Realtime Loop

Quest 3 specific checklist: [RUNBOOK_QUEST3.md](RUNBOOK_QUEST3.md).

### Start backend
0. Optional one-command startup:
```bash
python Gateway/scripts/dev_up.py --gateway-only
python Gateway/scripts/dev_up.py --with-inference
```
Evidence: `Gateway/scripts/dev_up.py`.
Optional hardened profile (v4.89):
```bash
# PowerShell
$env:BYES_GATEWAY_PROFILE="hardened"
python Gateway/scripts/dev_up.py --gateway-only
```
Evidence: `Gateway/main.py` (`_apply_gateway_profile_defaults`), `Gateway/byes/config.py` (`BYES_GATEWAY_PROFILE`).
1. Gateway:
```bash
python -m uvicorn main:app --app-dir Gateway --host 127.0.0.1 --port 8000
```
Evidence: `docs/English/COMMANDS.md:51`.
Quest LAN note:
- For Quest device testing, bind Gateway on `0.0.0.0` and use the PC LAN IP in Unity connection panel.
- Example: `python -m uvicorn main:app --app-dir Gateway --host 0.0.0.0 --port 8000`.
2. Optional inference service (for HTTP providers):
```bash
python -m uvicorn services.inference_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19120
```
Evidence: `docs/English/COMMANDS.md:57`; `Gateway/services/inference_service/README.md:13`.

### Start Unity
1. Open project with Unity `6000.3.5f2` (`ProjectSettings/ProjectVersion.txt:1`).
2. Default scene is `Assets/Scenes/SampleScene.unity` (BuildSettings enabled entry).
3. WS default address is `ws://127.0.0.1:8000/ws/events` (`Assets/Scenes/SampleScene.unity:2651`; `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:29,114`).

### Runtime controls
- Upload trigger key: `S` (`Assets/BeYourEyes/Unity/Interaction/ScanController.cs:22`).
- Live loop toggle key: `L` (Quest controller primary/A in `Quest3SmokeScene`).
- Quest manual scan trigger: right-hand trigger.
- Mode switch: `1/2/3` or `F1/F2/F3` (`Assets/Scripts/BYES/UI/ByesModeHotkeys.cs:10-20`).
- Confirm input: `Y/N` or XR primary/secondary (`Assets/Scripts/BYES/UI/ByesConfirmPanel.cs:100-120,294-300`).

### Success Signals
- Unity sends POST `/api/frame` (`Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:597`).
- Unity mode switch sends POST `/api/mode` (`Assets/Scripts/BYES/Core/ByesModeManager.cs:107-140`, `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:417-460`).
- Unity diagnostics panel can fetch `GET /api/version` and show `version/gitSha` (Quest smoke tooling).
- Gateway WS emits events from `/ws/events` (`Gateway/main.py:8280`).
- Unity presenter handles WS event `type` switch (`Assets/BeYourEyes/Presenters/Audio/SpeechOrchestrator.cs:162-178`).
- ACKs reach `/api/frame/ack` (`Assets/Scripts/BYES/Telemetry/ByesFrameTelemetry.cs:166`; `Gateway/main.py:1894`).
- Hardened profile smoke: `/api/mock_event` and `/api/run_package/upload` are blocked unless explicitly re-enabled (`Gateway/main.py`: `_ensure_dev_endpoints_enabled`, `_ensure_runpackage_upload_enabled`).

### Optional: Verify v4.90 mode profile takes effect
1. Set mode-profile env and restart Gateway:
```bash
# PowerShell example: read_text forces OCR every frame, walk throttles OCR
$env:BYES_MODE_PROFILE_JSON='{"default":{"ocr":{"every_n_frames":3},"risk":{"every_n_frames":1}},"read":{"ocr":{"every_n_frames":1}}}'
$env:BYES_EMIT_MODE_PROFILE_DEBUG='1'
python -m uvicorn main:app --app-dir Gateway --host 127.0.0.1 --port 8000
```
2. In Unity, switch mode (`1/2/3`) and trigger scan (`S`).
3. Observe:
- `/api/mode` accepted with `{"ok": true}` (`Gateway/main.py` `mode_change`).
- WS/events include `mode.profile` debug rows (when debug flag enabled) showing `targetsFired`/`targetsSkipped`.
Evidence:
- Config load: `Gateway/byes/config.py` (`BYES_MODE_PROFILE_JSON`, `BYES_EMIT_MODE_PROFILE_DEBUG`)
- Runtime mode resolution + consume changed flag: `Gateway/main.py` (`_resolve_mode_for_frame`)
- Stride decision function: `Gateway/byes/scheduler.py` (`should_run_mode_target`)
- Mode store: `Gateway/byes/mode_state.py` (`ModeStateStore`)

## Troubleshooting Quick Checks

| Symptom | Check | Evidence |
|---|---|---|
| WS not connected | Confirm `ws://127.0.0.1:8000/ws/events` and Gateway running | `Gateway/main.py:8280`; `SampleScene.unity:2651` |
| No frame accepted | Check `/api/frame` request payload and Gateway logs | `Gateway/main.py:1790-1820` |
| Upload fails | Validate zip format + manifest + safe extract rules | `Gateway/main.py:2128-2163`; `Gateway/scripts/report_run.py:2008-2017` |
| Contract lock mismatch | Run `python Gateway/scripts/verify_contracts.py --check-lock` | `.github/workflows/gateway-ci.yml:52`; `Gateway/scripts/verify_contracts.py:132,156` |
| Provider mismatch | Verify `BYES_*_BACKEND` and `*_HTTP_URL` envs | `Gateway/byes/config.py:469-481` |
| Hardening blocks requests unexpectedly | Check `BYES_GATEWAY_PROFILE`, `BYES_GATEWAY_DEV_ENDPOINTS_ENABLED`, `BYES_GATEWAY_RUNPACKAGE_UPLOAD_ENABLED`, `BYES_GATEWAY_ALLOW_LOCAL_RUNPACKAGE_PATH` | `Gateway/byes/config.py:355-367`; `Gateway/main.py:1955-1968` |
| 413 / 429 returned | Check request-size and rate-limit envs (`BYES_GATEWAY_MAX_*`, `BYES_GATEWAY_RATE_LIMIT_*`) | `Gateway/byes/config.py:359-366`; `Gateway/byes/middleware/request_size_limit.py`; `Gateway/byes/middleware/rate_limit.py` |
