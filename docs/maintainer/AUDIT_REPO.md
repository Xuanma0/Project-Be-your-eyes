# AUDIT_REPO

> Scope: repo-read evidence snapshot for maintainers. All facts below are backed by file paths + line references.

## Repo Snapshot

| Item | Value | Evidence |
|---|---|---|
| Branch (precheck) | `feature/unity-skeleton` | `git branch --show-current` (before docs branch creation) |
| Working branch (docs task) | `docs/audit-readme-refresh` | `git checkout -b docs/audit-readme-refresh` |
| HEAD commit | `c12e0ab4694a4b3d86ac7e19d1e1ddbb983f2c04` | `git rev-parse HEAD` |
| HEAD subject | `feat(v4.87): add mode change contract+api+events + mode metrics in report/leaderboard/linter/contract gate + unity mode manager v1` | `git show -s --format=%s HEAD` |
| Tags | `(none)` | `git tag --list` |
| Dirty status at precheck | `dirty` | `git status --porcelain=v1` showed modified Unity assets + untracked docs files |
| Stash action | `git stash push -u -m "codex-docs-prep"` | executed before doc generation to avoid overwriting local changes |
| Unity version | `6000.3.5f2` | `ProjectSettings/ProjectVersion.txt:1` |
| Enabled build scenes | `Assets/Scenes/SampleScene.unity` | `ProjectSettings/EditorBuildSettings.asset` |

## Stack Breakdown

- Unity client (`Assets/`, `ProjectSettings/`, `*.csproj`).
- Gateway runtime: FastAPI app (`Gateway/main.py:1731`).
- Planner service: Flask app (`Gateway/services/planner_service/app.py:19,589,774-777`).
- Inference/reference services: FastAPI (`Gateway/services/*/app.py`).
- CI: GitHub Actions (`.github/workflows/gateway-ci.yml:1-53`).

## Key Entrypoints

- Unity bootstrap: `Assets/BeYourEyes/AppBootstrap.cs:51-93` (`EnsureRuntimeLoop` adds `GatewayWsClient`/fallback `GatewayPoller`).
- Unity default scene: `Assets/Scenes/SampleScene.unity` (enabled in BuildSettings).
- Demo scene exists and also points to WS: `Assets/Scenes/DemoScene.unity:972`.
- Gateway HTTP/WS entry: `Gateway/main.py` (`/api/frame` at `1790`, `/ws/events` at `8280`).

## Offline Evaluation Chain

`RunPackage -> events_v1 -> report -> regression gate`

1. Chain definition documented in `Gateway/README.md:7`.
2. Replay sends frames to `/api/frame` (`Gateway/scripts/replay_run_package.py:263,324`; `Gateway/main.py:1790`).
3. Replay normalizes WS events into `events/events_v1.jsonl` (`Gateway/scripts/replay_run_package.py:402-403`).
4. Report generated via `generate_report_outputs(...)` (`Gateway/scripts/replay_run_package.py:428`; `Gateway/scripts/report_run.py:905`).
5. Regression gate enforces critical-fn failure (`Gateway/scripts/run_regression_suite.py:1220,1602`).
6. CI executes pytest + regression + contract lock check (`.github/workflows/gateway-ci.yml:32-53`).

## Realtime Closed Loop

1. Unity capture/upload: `FrameCapture` -> `GatewayClient.TrySendFrameDetailed` (`Assets/BeYourEyes/Unity/Capture/FrameCapture.cs:352`) -> `/api/frame` (`Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:597`).
2. Gateway ingest: `/api/frame` accepts image/form and emits `frame.input` event (`Gateway/main.py:1790-1861`).
3. Event stream: `/ws/events` (`Gateway/main.py:8280-8302`).
4. Legacy vs envelope switch: `GATEWAY_SEND_ENVELOPE` (`Gateway/byes/config.py:344`; `Gateway/main.py:1695-1699`; `Gateway/byes/fusion.py:303-404`).
5. v1 inference WS switch: `BYES_INFERENCE_EMIT_WS_V1` (`Gateway/byes/config.py:559`; `Gateway/main.py:737-744`).
6. Unity consumers: `GatewayClient.HandleWsMessage` (`Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:785-852`) and `SpeechOrchestrator` type switch (`Assets/BeYourEyes/Presenters/Audio/SpeechOrchestrator.cs:162-178`).
7. Feedback ACK: Unity posts `/api/frame/ack` (`Assets/Scripts/BYES/Telemetry/ByesFrameTelemetry.cs:166`) and Gateway persists ack event (`Gateway/main.py:1894-1942`).

## Version Surface (`v4.*`)

- `git tag` is empty (no canonical release tag at precheck).
- HEAD subject indicates `v4.87` (commit message).
- Multiple docs still mention historical `v4.x` ranges (for example `docs/English/RELEASE_NOTES.md` currently `v4.38 -> v4.82`).
- Recommendation: use root `VERSION` as current-dev single source; keep historical timeline only in release notes.
