# Command Index (PowerShell)

## Test & Validation

1. Run Gateway tests:

```powershell
cd Gateway
python -m pytest -q
```

2. Lint run package fixture:

```powershell
python scripts/lint_run_package.py --run-package tests/fixtures/run_package_with_events_v1_min
```

3. Run regression suite with gates:

```powershell
cd ..
python Gateway/scripts/run_regression_suite.py --suite Gateway/regression/suites/baseline_suite.json --baseline Gateway/regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
```

## Replay & Report

4. Replay a fixture:

```powershell
python Gateway/scripts/replay_run_package.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min --reset
```

5. Generate one report:

```powershell
python Gateway/scripts/report_run.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min
```

6. Batch report packages:

```powershell
python Gateway/scripts/report_packages.py --root Gateway/tests/fixtures --out "$env:TEMP\byes_reports"
```

## Runtime / Dashboard

7. Start Gateway:

```powershell
cd Gateway
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

8. Start inference_service:

```powershell
python -m uvicorn services.inference_service.app:app --host 127.0.0.1 --port 19120
```

## Optimization & Calibration (Optional)

9. Sweep ONNX depth input sizes:

```powershell
python Gateway/scripts/sweep_depth_input_size.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min --sizes 518,384,256 --out "$env:TEMP\depth_sweep.json" --port 19120 --risk-url http://127.0.0.1:19120/risk
```

10. Calibrate risk thresholds:

```powershell
python Gateway/scripts/calibrate_risk_thresholds.py --run-package Gateway/tests/fixtures/run_package_risk_calib_10f --risk-url http://127.0.0.1:19120/risk --sizes 256 --out "$env:TEMP\risk_calib_out.json"
```

## v4.82 Depth Temporal (DA3 Fixture Path)

11. Generate report for the temporal-depth fixture:

```powershell
python Gateway/scripts/report_run.py --run-package Gateway/tests/fixtures/run_package_with_depth_temporal_min
```

Inspect:
- `quality.depthTemporal.jitterAbs.p90`
- `quality.depthTemporal.flickerRateNear.mean`
- `quality.depthTemporal.scaleDriftProxy.p90`
- `quality.depthTemporal.refViewStrategyDiversityCount`

12. Run contract suite gate for depth temporal:

```powershell
python Gateway/scripts/run_regression_suite.py --suite Gateway/regression/suites/contract_suite.json --baseline Gateway/regression/baselines/baseline.json --fail-on-drop
```

Look for run `fixture_with_depth_temporal_contract` with:
- `depthEventsPresent=True`
- `depthPayloadSchemaOk=True`
- `depthTemporalPresent=True`

13. Run benchmark matrix with DA3 temporal profile (`replay=0`):

```powershell
cd Gateway
python scripts/run_dataset_benchmark.py --root artifacts/imports/v468_ego4d_demo --out artifacts/benchmarks/v482_demo --matrix 1 --profiles scripts/profiles/v482_depth_temporal_profiles.json --replay 0 --shuffle 0 --max 10
```

## Contracts / Models / SLAM (Cross-Version)

14. Verify contracts lock:

```powershell
python Gateway/scripts/verify_contracts.py --check-lock
```

15. Verify model/artifact requirements:

```powershell
python Gateway/scripts/verify_models.py --check --quiet
```

16. Ingest pySLAM TUM trajectory into `slam.pose` events:

```powershell
python Gateway/scripts/ingest_pyslam_tum.py --run-package <run_package_dir> --tum <trajectory.tum> --align-mode auto --replace-existing 1
```

17. Evaluate SLAM trajectory error (`ATE/RPE`) against GT TUM:

```powershell
python Gateway/scripts/eval_slam_tum.py --run-package <run_package_dir>
```
