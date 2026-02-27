# MAINTAINER_BRIEF

## 1) Current Version + Entrypoints
- Current development version signal: `v4.87` (HEAD subject).
- Gateway entry: `Gateway/main.py:1731` (`FastAPI app`).
- Primary APIs: `/api/frame` (`Gateway/main.py:1790`) and `/ws/events` (`Gateway/main.py:8280`).
- Unity default build scene: `Assets/Scenes/SampleScene.unity`.

## 2) Two Run Paths

### Offline evaluation path
1. `python -m pytest -q -n auto --dist loadgroup` (under `Gateway/`).
2. `python Gateway/scripts/replay_run_package.py --run-package ... --reset`.
3. `python Gateway/scripts/report_run.py --run-package ...`.
4. `python Gateway/scripts/run_regression_suite.py --suite ... --fail-on-critical-fn`.
Success markers: `events/events_v1.jsonl`, `report.json`, regression pass.

### Unity realtime path
1. Start Gateway on `127.0.0.1:8000`.
2. (Optional) Start inference_service on `127.0.0.1:19120`.
3. Open `Assets/Scenes/SampleScene.unity` and run.
4. Press `S` to trigger upload; monitor `/ws/events` flow.
Success markers: `/api/frame` accepted, WS events consumed, `/api/frame/ack` feedback observed.

## 3) Top 5 Risks / Tech Debt
1. No built-in auth middleware on Gateway API/WS surface.
2. Upload/decompress endpoint can be resource-abused without edge controls.
3. Version source-of-truth is split (HEAD subject vs docs vs no tags).
4. Planner API key naming mismatch (`OPENAI_API_KEY` vs `BYES_PLANNER_LLM_API_KEY`) can confuse operations.
5. Deployment profile ambiguity (localhost docs vs `0.0.0.0` external Dockerfiles).

## 4) Recommended Next Iteration Order
1. Finalize versioning policy (`VERSION` + release tag cadence).
2. Stabilize configuration policy (planner key compatibility + env docs).
3. Publish hardened deployment guide (reverse proxy/auth/TLS/rate-limit).
4. Add CI guard for Unity `.meta` completeness and docs link checks.
5. Decide ASR product scope before API expansion.
