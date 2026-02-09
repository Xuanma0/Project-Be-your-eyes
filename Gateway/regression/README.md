# Regression Suite

## Run
```bash
python Gateway/scripts/run_regression_suite.py \
  --suite Gateway/regression/suites/baseline_suite.json \
  --baseline Gateway/regression/baselines/baseline.json \
  --fail-on-drop
```

## Update Baseline
```bash
python Gateway/scripts/run_regression_suite.py \
  --suite Gateway/regression/suites/baseline_suite.json \
  --baseline Gateway/regression/baselines/baseline.json \
  --write-baseline
```

## Failure Rules
- `qualityScore` drop greater than `2.0` points when `--fail-on-drop`.
- Suite `expected` constraints (for example `minQualityScore`, `maxConfirmTimeouts`).

On failures the runner prints each run delta and the first findings from report output.
