# 5-Minute Demo (Professor / Reviewer)

This demo uses built-in fixtures only. No model download required.

## 0) Prerequisite

```powershell
cd Gateway
python -m pytest -q
```

Expected: tests pass.

## 1) Replay A Fixture

```powershell
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_risk_gt_min --reset
```

What this does:
- replays frames and metadata,
- produces `events/events_v1.jsonl`,
- writes replay artifacts under fixture replay output.

## 2) Generate Report

```powershell
python scripts/report_run.py --run-package tests/fixtures/run_package_with_risk_gt_min
```

Check:
- `report.json`
- `report.md`

Focus fields:
- `inference.risk`
- `quality.depthRisk.critical.missCriticalCount`
- `quality.riskLatencyMs`
- `quality.qualityScore`

## 3) Run Regression Gate

```powershell
cd ..
python Gateway/scripts/run_regression_suite.py --suite Gateway/regression/suites/baseline_suite.json --baseline Gateway/regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
```

Expected:
- each fixture prints score and `critical_fn`,
- exit code `0` when no regression.

## 4) Open Leaderboard

Start Gateway app:

```powershell
cd Gateway
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Then open:
- `http://127.0.0.1:8000/runs`
- `http://127.0.0.1:8000/api/run_packages`

Look for:
- `Quality`
- `ConfirmTimeouts`
- `Critical FN`
- `Risk p90(ms)`

## Optional: Real ONNX Depth Extension

If you want to show real depth inference:

1. Install optional deps:

```powershell
python -m pip install -r Gateway/services/inference_service/requirements-onnx-depth.txt
```

2. Prepare model outside repo (example):
- `D:\models\depth_anything_v2_small\model.onnx`

3. Validate model:

```powershell
python Gateway/services/inference_service/tools/verify_depth_onnx.py --path D:\models\depth_anything_v2_small\model.onnx --expected-sha256 <sha256>
```

4. Run `inference_service` with ONNX depth and repeat replay/report.
