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

## Optional: v4.82 Temporal Depth Consistency Demo (Fixture)

1. Generate report from the temporal fixture:

```powershell
python Gateway/scripts/report_run.py --run-package Gateway/tests/fixtures/run_package_with_depth_temporal_min
```

2. Check `report.json`:
- `quality.depthTemporal.present`
- `quality.depthTemporal.jitterAbs.p90`
- `quality.depthTemporal.flickerRateNear.mean`
- `quality.depthTemporal.scaleDriftProxy.p90`

3. Run matrix summary with DA3 temporal profile:

```powershell
cd Gateway
python scripts/run_dataset_benchmark.py --root artifacts/imports/v468_ego4d_demo --out artifacts/benchmarks/v482_demo --matrix 1 --profiles scripts/profiles/v482_depth_temporal_profiles.json --replay 0 --shuffle 0 --max 10
```

4. Open:
- `artifacts/benchmarks/v482_demo/summary.md`

Confirm columns:
- `depthJitterP90(p90)`
- `depthFlickerMean(mean)`
- `depthScaleDriftP90(p90)`
- `depthRefViewDiversity(mean)`

## Optional: Cross-Version Matrix Presets

Use profile files to compare historical capability tracks without changing code:

```powershell
cd Gateway
python scripts/run_dataset_benchmark.py --root artifacts/imports/v468_ego4d_demo --out artifacts/benchmarks/v4x_compare --matrix 1 --profiles scripts/profiles/v481_costmap_dynamic_profiles.json --replay 0 --shuffle 0 --max 10
```

Profile examples:
- `baseline_reference`
- `costmap_fused_local_tracking`
- `da3_fixture_depth_temporal` (in `v482_depth_temporal_profiles.json`)
