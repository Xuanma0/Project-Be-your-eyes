# Project-Be-your-eyes

[中文说明 / Chinese Version](docs/Chinese/README.md)

Project-Be-your-eyes (Be Your Eyes) is an event-driven assistive perception system for Unity + Gateway + pluggable inference, with replayable evaluation and safety gating for `risk + ocr` pipelines.

## Why This Project

- Replayable `RunPackage`: deterministic offline evaluation from recorded frames/events/metrics.
- Unified events schema: `events/events_v1.jsonl` for tool results and latency evidence.
- Report + quality metrics: `report.json` and markdown report with OCR/risk/safety breakdown.
- Leaderboard for runs: filter/sort by quality, latency, confirm timeouts, critical misses.
- Regression gate in CI: score-drop checks plus hard safety gate (`critical FN == 0`).
- Pluggable inference: mock/http backends; optional real OCR and ONNX depth providers.

## Quick Start (PowerShell)

### 1) Prepare Python environment (required for Gateway)

Option A: `venv`

```powershell
cd Gateway
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

Option B: conda

```powershell
cd Gateway
conda create -n byes python=3.11 -y
conda activate byes
python -m pip install -U pip
python -m pip install -r requirements.txt
```

### 2) Run Gateway tests only

```powershell
cd Gateway
python -m pytest -q
```

### 3) Minimal replay

```powershell
cd ..
python Gateway/scripts/replay_run_package.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min --reset
```

### 4) Generate report

```powershell
python Gateway/scripts/report_run.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min
```

### 5) Run regression

```powershell
python Gateway/scripts/run_regression_suite.py --suite Gateway/regression/suites/baseline_suite.json --baseline Gateway/regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
```

## POV-compiler -> BYE Contract

- Single source schema: `schemas/pov_ir_v1.schema.json`
- Ingest POV IR to BYES events v1:

```powershell
python Gateway/scripts/ingest_pov_ir.py --run-package <run_package_dir> --pov-ir <pov_ir.json> --strict 1
```

- Run contract regression suite:

```powershell
python Gateway/scripts/run_regression_suite.py --suite Gateway/regression/suites/contract_suite.json --baseline Gateway/regression/baselines/baseline.json --fail-on-drop
```

## Optional: Real ONNX Depth (Depth Anything V2 Small)

### Install optional deps

```powershell
python -m pip install -r Gateway/services/inference_service/requirements-onnx-depth.txt
```

### Download model (do not store in repo)

- Model: `onnx-community/depth-anything-v2-small -> onnx/model.onnx`
- Example local path: `D:\models\depth_anything_v2_small\model.onnx`

### Verify sha256

```powershell
python Gateway/services/inference_service/tools/verify_depth_onnx.py --path D:\models\depth_anything_v2_small\model.onnx --expected-sha256 <sha256_from_hf_page>
```

### Start inference_service (HTTP + ONNX depth)

```powershell
cd Gateway
$env:BYES_SERVICE_RISK_PROVIDER="heuristic"
$env:BYES_SERVICE_DEPTH_PROVIDER="onnx"
$env:BYES_SERVICE_DEPTH_ONNX_PATH="D:\models\depth_anything_v2_small\model.onnx"
$env:BYES_SERVICE_DEPTH_MODEL_ID="depth-anything-v2-small-onnx"
$env:BYES_SERVICE_DEPTH_INPUT_SIZE="256"
$env:BYES_SERVICE_RISK_DEBUG="1"
python -m uvicorn services.inference_service.app:app --host 127.0.0.1 --port 19120
```

### Sweep input size (518/384/256)

```powershell
python Gateway/scripts/sweep_depth_input_size.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min --sizes 518,384,256 --out "$env:TEMP\byes_depth_sweep.json" --port 19120 --risk-url http://127.0.0.1:19120/risk
```

Default ONNX depth input size is now calibrated and fixed to `256` (still env-overridable).

## How We Evaluate Safety And Usefulness

`qualityScore` is penalty-based and emphasizes safety first:

- Critical misses (`critical FN`) are treated as hard safety risk.
- Confirm timeout / missing response are penalized.
- Depth-risk FP/FN and delay are penalized by risk quality terms.
- OCR mismatch metrics (CER/WER/exact match) contribute when OCR GT exists.
- Risk latency is tracked (`p50/p90/p99/max`) for performance visibility.

Example `report.json` snippet:

```json
{
  "inference": {
    "risk": {"backend": "http", "model": "heuristic-risk-v2+depth=depth-anything-v2-small-onnx", "endpoint": "http://127.0.0.1:19120/risk"}
  },
  "quality": {
    "depthRisk": {
      "critical": {"missCriticalCount": 0},
      "detectionDelayFrames": {"p90": 0, "max": 0}
    },
    "riskLatencyMs": {"count": 10, "p50": 88, "p90": 131, "max": 168},
    "qualityScore": 89.0,
    "qualityScoreBreakdown": {"risk": 42.0, "ocr": 25.0, "safetyBehavior": 22.0}
  }
}
```

## Key Directories

```text
Gateway/                              # core gateway runtime + APIs + tests
Gateway/services/inference_service/   # pluggable OCR/risk/depth inference service
Gateway/scripts/                      # replay/report/regression/sweep/calibration tools
Gateway/regression/                   # suite definitions, baselines, outputs
docs/                                 # architecture/demo/glossary/commands docs
Assets/                               # Unity client and scene integration
```

## Milestones (v4.9 -> v4.29)

| Version | Theme | What Was Added |
|---|---|---|
| v4.9 | Replayable inputs | RunPackage replay flow and fixture-based reproducibility |
| v4.13-v4.15 | Event standard + CI | `events_v1` schema, recorder compatibility, regression suite in CI |
| v4.16-v4.21 | Pluggable inference | OCR/risk backend registry (mock/http), depth-aware risk evolution |
| v4.23-v4.26 | ONNX depth + observability | ONNX depth provider, input-size sweep, latency breakdown, leaderboard latency columns |
| v4.27-v4.29 | Calibration + safety gate | Threshold calibration loop, `critical FN` explainability, defaults solidified, regression/CI gate for `critical FN == 0` |

## Where To Read Next

- Gateway developer/evaluation guide: `Gateway/README.md`
- Inference provider/deployment guide: `Gateway/services/inference_service/README.md`
- System architecture: `docs/ARCHITECTURE.md`
- 5-minute demo script: `docs/QUICK_DEMO.md`
- Terms: `docs/GLOSSARY.md`
- Command index: `docs/COMMANDS.md`
