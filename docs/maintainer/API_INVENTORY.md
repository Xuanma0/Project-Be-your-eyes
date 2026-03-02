# API_INVENTORY

## Gateway Public Surface (`Gateway/main.py`)

| Method | Path | Purpose | Request Schema / Fields | Response | Primary Callers | Evidence |
|---|---|---|---|---|---|---|
| GET | `/api/health` | Gateway health/degradation status | No explicit request body. | JSON dict/list (see handler). | Unity gateway status check (`Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:1065`) | `Gateway/main.py:1746` (`health`) |
| GET | `/api/mock_event` | Dev mock event endpoint | No explicit request body. | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:1776` (`mock_event`) |
| GET | `/api/tools` | Tool inventory/status snapshot | No explicit request body. | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:1781` (`list_tools`) |
| GET | `/api/external_readiness` | External dependency readiness | No explicit request body. | JSON dict/list (see handler). | Unity capability status check (`Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:1122`) | `Gateway/main.py:1786` (`external_readiness`) |
| POST | `/api/frame` | Primary frame ingest | Multipart form/image bytes + optional `meta` (see `Gateway/main.py:1791-1799`). | JSON dict/list (see handler). | Unity (`Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:597`); replay script (`Gateway/scripts/replay_run_package.py:263`); manual curl (`Gateway/README.md:1075`) | `Gateway/main.py:1791` (`frame`) |
| POST | `/api/frame/ack` | User feedback ACK ingest | `FrameAckRequest` (`Gateway/main.py:416`). | JSON dict/list (see handler). | Unity telemetry (`Assets/Scripts/BYES/Telemetry/ByesFrameTelemetry.cs:166`); manual curl (`Gateway/README.md:1080`) | `Gateway/main.py:1895` (`frame_ack`) |
| POST | `/api/mode` | Mode change event ingest + runtime mode-state update | `ModeChangeRequest` (`runId`, `frameSeq`, `mode`, `source`, `tsMs`, `deviceId`, optional `runPackage`). | JSON dict/list (`ok`, `runId`, `frameSeq`, `mode`, `source`, `tsMs`). | Unity mode manager (`Assets/Scripts/BYES/Core/ByesModeManager.cs:107-140`) via `GatewayClient.PostModeChange` (`Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:417-460`). | `Gateway/main.py` (`@app.post("/api/mode") mode_change, gateway.mode_state.set_mode`) |
| GET | `/api/mode` | Read current mode snapshot for device runtime | Query: `deviceId` optional. Reads in-memory mode state, not event replay. | JSON dict (`deviceId`, `mode`, `updatedTsMs`, `expiresInMs`, `source`). | Unity runtime panel / manual health check. | `Gateway/main.py` (`@app.get("/api/mode") mode_get`); `Gateway/byes/mode_state.py` (`get_device_snapshot`); `Assets/Scripts/BYES/UI/ByesConnectionPanel.cs` (`ReadModeRoutine`) |
| POST | `/api/ping` | Lightweight RTT and connectivity probe | `PingRequest` (`deviceId`, `seq`, `clientSendTsMs`). | JSON dict (`deviceId`, `seq`, `clientSendTsMs`, `serverRecvTsMs`, `serverSendTsMs`). | Unity runtime panel / manual diagnostics. | `Gateway/main.py` (`@app.post("/api/ping") ping`); `Assets/Scripts/BYES/UI/ByesConnectionPanel.cs` (`PingRoutine`) |
| GET | `/api/version` | Lightweight build/version diagnostics | No explicit request body. | JSON dict (`version`, `gitSha`, `startedTsMs`, `uptimeSec`, `profile`). | Unity runtime panel / manual diagnostics. | `Gateway/main.py` (`@app.get("/api/version") api_version`); `Gateway/byes/version_info.py`; `Assets/Scripts/BYES/UI/ByesConnectionPanel.cs` (`GetVersionRoutine`) |
| GET | `/api/capabilities` | Runtime provider/feature matrix for Quest self-test and diagnostics | No explicit request body. | JSON dict (`version`, `available_providers`, `enabled_flags`, `mode_profile`). | Quest panel + self-test (`Assets/Scripts/BYES/Quest/ByesQuest3SelfTestRunner.cs`). | `Gateway/main.py` (`@app.get("/api/capabilities") api_capabilities`) |
| POST | `/api/assist` | Run selected targets from latest cached frame (no re-upload required when cache is fresh) | `AssistRequest` (`deviceId`, `action|targets`, optional `prompt`, optional `roi`, `maxAgeMs`, optional `runId`, optional `mode`). | JSON dict (`ok`, `runId`, `frameSeq`, `targets`, `cacheAgeMs`). | Quest panel/menu find/read/detect quick actions (`Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`). | `Gateway/main.py` (`@app.post("/api/assist") api_assist`), `Gateway/byes/frame_cache.py` |
| POST | `/api/record/start` | Start Quest recording session for a device | `RecordStartRequest` (`deviceId`, optional `note`, optional `maxSec`, optional `maxFrames`). | JSON dict (`ok`, `runId`, `recordingPath`, `startedTsMs`). | Quest menu action (`Start Record`). | `Gateway/main.py` (`@app.post("/api/record/start") api_record_start`), `Gateway/byes/recording/manager.py` |
| POST | `/api/record/stop` | Stop Quest recording session and finalize run package-like artifact | `RecordStopRequest` (`deviceId`). | JSON dict (`ok`, `runId`, `recordingPath`, `manifestPath`, `framesCount`, `eventCount`). | Quest menu action (`Stop Record`). | `Gateway/main.py` (`@app.post("/api/record/stop") api_record_stop`), `Gateway/byes/recording/manager.py` |
| POST | `/api/fault/set` | Inject fault (dev) | `FaultSetRequest` (`Gateway/main.py:263`). | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:2026` (`fault_set`) |
| POST | `/api/fault/clear` | Clear fault (dev) | No explicit request body. | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:2040` (`fault_clear`) |
| POST | `/api/dev/reset` | Reset runtime state (dev) | No explicit request body. | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:2046` (`dev_reset`) |
| POST | `/api/dev/intent` | Inject intent (dev) | `IntentRequest` (`Gateway/main.py:270`). | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:2052` (`dev_intent`) |
| POST | `/api/dev/crosscheck` | Crosscheck diagnostic (dev) | `CrossCheckRequest` (`Gateway/main.py:296`). | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:2068` (`dev_crosscheck`) |
| POST | `/api/dev/performance` | Performance diagnostic (dev) | `PerformanceRequest` (`Gateway/main.py:301`). | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:2078` (`dev_performance`) |
| GET | `/api/confirm/pending` | Query pending confirm | Query/Form parameters (see handler signature). | JSON dict/list (see handler). | Unity pending-confirm poll (`Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:491`) | `Gateway/main.py:2088` (`confirm_pending`) |
| POST | `/api/confirm` | Submit confirm (legacy) | `ConfirmSubmitRequest` (`Gateway/main.py:307`). | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:2098` (`confirm_submit`) |
| POST | `/api/run_package/upload` | Upload zip + generate report + index | Multipart form with `file: .zip` (`Gateway/main.py:2129-2136`). | JSON dict/list (see handler). | Unity run upload (`Assets/BeYourEyes/Adapters/Networking/RunPackageManager.cs:968`); replay helper (`Gateway/scripts/replay_run_package.py:449`) | `Gateway/main.py:2129` (`run_package_upload`) |
| POST | `/api/pov/ingest` | Ingest POV IR | JSON object payload (`Gateway/main.py:2232`). | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:2232` (`ingest_pov_ir`) |
| GET | `/api/pov/latest` | Read latest POV IR | Query/Form parameters (see handler signature). | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:2293` (`get_latest_pov`) |
| GET | `/api/seg/context` | Build seg context from events | Query/Form parameters (see handler signature). | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:2304` (`get_seg_context`) |
| GET | `/api/slam/context` | Build slam context from events | Query/Form parameters (see handler signature). | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:2353` (`get_slam_context`) |
| GET | `/api/plan/context` | Build plan context pack | Query/Form parameters (see handler signature). | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:2448` (`get_plan_context`) |
| GET | `/api/contracts` | Contract lock index endpoint | No explicit request body. | `byes.contracts.index.v1` payload (`Gateway/main.py:2564`) sourced from `Gateway/contracts/contract.lock.json`. | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:2554` (`contracts_index`) |
| GET | `/api/models` | Model manifest endpoint | No explicit request body. | `byes.models.v1` manifest (`Gateway/main.py:2574-2575`; `Gateway/byes/model_manifest.py:393`). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:2574` (`models_index`) |
| POST | `/api/pov/context` | Build POV context pack | `PovContextRequest` (`Gateway/main.py:326`). | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:2589` (`build_pov_context`) |
| POST | `/api/plan` | Generate action plan | `PlanGenerateRequest` (`Gateway/main.py:390`) + optional query `provider`. | JSON dict/list (see handler). | Unity plan client (`Assets/Scripts/BYES/Plan/PlanClient.cs:95`); manual curl (`Gateway/README.md:843`) | `Gateway/main.py:2641` (`generate_plan`) |
| POST | `/api/plan/execute` | Execute action plan + emit UI events | `PlanExecuteRequest` (`Gateway/main.py:409`). | JSON dict/list (see handler). | Unity plan client (`Assets/Scripts/BYES/Plan/PlanClient.cs:141`); manual curl (`Gateway/README.md:888`) | `Gateway/main.py:2934` (`execute_plan`) |
| POST | `/api/confirm/response` | Submit confirm response v1 | `ConfirmResponseRequest` (`Gateway/main.py:455`). | JSON dict/list (see handler). | Unity plan client (`Assets/Scripts/BYES/Plan/PlanClient.cs:212`) | `Gateway/main.py:3007` (`confirm_response`) |
| GET | `/api/run_packages` | List/filter run packages | Query/Form parameters (see handler signature). | JSON dict/list (see handler). | Unity run history UI (`Assets/BeYourEyes/Adapters/Networking/RunHistoryClient.cs:37`) | `Gateway/main.py:3103` (`run_packages_list`) |
| GET | `/api/run_packages/export.json` | Export run list JSON | Query/Form parameters (see handler signature). | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:3385` (`run_packages_export_json`) |
| GET | `/api/run_packages/export.csv` | Export run list CSV | Query/Form parameters (see handler signature). | JSON dict/list (see handler). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:3576` (`run_packages_export_csv`) |
| GET | `/api/run_packages/{run_id}/summary` | Get run summary | Query/Form parameters (see handler signature). | JSON dict/list (see handler). | Unity run history UI (`Assets/BeYourEyes/Adapters/Networking/RunHistoryClient.cs:88`) | `Gateway/main.py:7096` (`run_package_summary`) |
| GET | `/api/run_packages/{run_id}/report` | Download run report markdown | Query/Form parameters (see handler signature). | FileResponse markdown (`Gateway/main.py:7103-7111`). | Unity run history UI (`Assets/BeYourEyes/Adapters/Networking/RunHistoryClient.cs:126`) | `Gateway/main.py:7104` (`run_package_report`) |
| GET | `/api/run_packages/{run_id}/zip` | Download run package zip | Query/Form parameters (see handler signature). | FileResponse zip (`Gateway/main.py:7114-7122`). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:7115` (`run_package_zip`) |
| GET | `/runs` | Runs dashboard HTML | Query/Form parameters (see handler signature). | HTMLResponse (`Gateway/main.py:7125`). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:7126` (`runs_dashboard`) |
| GET | `/runs/compare` | Runs compare HTML | Query/Form parameters (see handler signature). | HTMLResponse (`Gateway/main.py:8108`). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:8109` (`runs_compare_page`) |
| GET | `/runs/{run_id}` | Run detail HTML | Query/Form parameters (see handler signature). | HTMLResponse (`Gateway/main.py:8187`). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:8188` (`run_details_page`) |
| GET | `/metrics` | Prometheus metrics | No explicit request body. | Prometheus response (`Gateway/main.py:8274-8277`). | Manual/API consumer (no single in-repo caller evidenced). | `Gateway/main.py:8275` (`metrics`) |
| WEBSOCKET | `/ws/events` | Realtime websocket event stream | No explicit request body. | WebSocket text/json stream (`Gateway/main.py:8280-8302`). | Unity WS clients (`Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:29`, `GatewayWsClient.cs:19`); replay client (`Gateway/scripts/replay_run_package.py:114`) | `Gateway/main.py:8281` (`ws_events`) |

## v4.89 Endpoint Guard Toggles

| Guard | Affected Endpoints | Default (`local`) | Hardened Default | Evidence |
|---|---|---|---|---|
| `BYES_GATEWAY_DEV_ENDPOINTS_ENABLED` | `/api/mock_event`, `/api/fault/*`, `/api/dev/*` | enabled | disabled | `Gateway/main.py` (`_ensure_dev_endpoints_enabled`) |
| `BYES_GATEWAY_RUNPACKAGE_UPLOAD_ENABLED` | `/api/run_package/upload` | enabled | disabled | `Gateway/main.py` (`_ensure_runpackage_upload_enabled`) |
| `BYES_GATEWAY_ALLOW_LOCAL_RUNPACKAGE_PATH` | Context APIs that accept `runPackage` local paths | enabled | disabled | `Gateway/main.py` (`_resolve_context_run_package_input`) |
| `BYES_GATEWAY_API_KEY` | Guarded HTTP routes + `/ws/events` | disabled | disabled unless explicitly set | `Gateway/main.py` (`_gateway_guardrails`, `_ws_guardrails_ok`) |

Profile defaults are applied in `Gateway/main.py` via `_apply_gateway_profile_defaults` when `BYES_GATEWAY_PROFILE=hardened`.

## v4.90 Mode-Synced Scheduling Notes

- Mode write path: Unity mode hotkey/UI -> `GatewayClient.PostModeChange` -> `POST /api/mode` -> `gateway.mode_state.set_mode(...)`.
- Mode read path for frame scheduling: `submit_frame(...)` resolves mode/device (`_resolve_mode_for_frame`) and `_run_inference_for_frame(...)` applies `should_run_mode_target(...)`.
- Endpoint auth note: when `BYES_GATEWAY_API_KEY` is set, both `GET /api/mode` and `POST /api/ping` require `X-BYES-API-Key` (same `/api/*` guard policy).
- Optional per-mode stride source: `BYES_MODE_PROFILE_JSON` (empty = legacy behavior).
- Optional observability: `BYES_EMIT_MODE_PROFILE_DEBUG=1` emits `mode.profile` debug events with fired/skipped targets.
- Evidence:
  - `Gateway/byes/mode_state.py`
  - `Gateway/byes/scheduler.py` (`should_run_mode_target`)
  - `Gateway/main.py` (`_resolve_mode_for_frame`, `_run_inference_for_frame`, `mode_change`)

## WebSocket Event Modes

| Mode | Switch | Payload Form | Evidence |
|---|---|---|---|
| Legacy event | `GATEWAY_SEND_ENVELOPE=false` (default) | `fusion.to_legacy_event(event)` (risk/perception/action_plan/health + dialog mapping) | `Gateway/byes/config.py:344`; `Gateway/main.py:1695-1699`; `Gateway/byes/fusion.py:303-404`; `Gateway/byes/schema.py:233` |
| Envelope event | `GATEWAY_SEND_ENVELOPE=true` | Full `EventEnvelope` JSON | `Gateway/main.py:1695-1696`; `Gateway/byes/schema.py:16-23` |
| Inference v1 direct | `BYES_INFERENCE_EMIT_WS_V1=true` | `byes.event.v1` rows (tool/frame/plan events) | `Gateway/byes/config.py:559`; `Gateway/main.py:737-744`; `Gateway/byes/inference/event_emitters.py:70,132,176,220,264` |

Unity parsing points: `GatewayClient.HandleWsMessage` (`Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:785-852`), `SpeechOrchestrator` (`Assets/BeYourEyes/Presenters/Audio/SpeechOrchestrator.cs:162-178`), legacy poller (`Assets/BeYourEyes/Adapters/Networking/GatewayPoller.cs:99-106`).

## Service Inventory (`Gateway/services/*/app.py`)

| Service | Routes | Typical Port / Bind Evidence | Called By |
|---|---|---|---|
| `inference_service` | `GET /healthz`, `POST /ocr`, `POST /risk`, `POST /det`, `POST /seg`, `POST /depth`, `POST /slam/pose` | `docs/English/COMMANDS.md:57` (`127.0.0.1:19120`) | Gateway `/api/frame` via HTTP backends (`Gateway/byes/inference/registry.py`) |
| `planner_service` | `GET /healthz`, `POST /plan` | defaults `PLANNER_SERVICE_HOST=127.0.0.1`, `PLANNER_SERVICE_PORT=19211` (`Gateway/services/planner_service/app.py:775-777`) | Gateway plan backend (`Gateway/byes/planner_backends/http.py:15`; `/api/plan`) |
| `reference_seg_service` | `GET /healthz`, `POST /seg` | `Gateway/services/inference_service/README.md:103` (`19231`) | inference_service when seg provider points to reference endpoint |
| `reference_depth_service` | `GET /healthz`, `POST /depth` | `Gateway/services/inference_service/README.md:173` (`19241`) | inference_service depth provider chain |
| `reference_ocr_service` | `GET /healthz`, `POST /ocr` | `Gateway/services/inference_service/README.md:135` (`19251`) | inference_service ocr provider chain |
| `reference_slam_service` | `GET /healthz`, `POST /slam/pose` | `Gateway/services/inference_service/README.md:243` (`19261`) | inference_service slam provider chain |
| `sam3_seg_service` | `GET /healthz`, `POST /seg` | `Gateway/services/inference_service/README.md:205` (`19271`) | inference_service seg provider alternative |
| `da3_depth_service` | `GET /healthz`, `POST /depth` | `Gateway/services/inference_service/README.md:188` (`19281`) | inference_service depth provider alternative |
