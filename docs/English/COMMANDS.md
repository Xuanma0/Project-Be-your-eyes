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
