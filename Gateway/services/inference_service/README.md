# Inference Service Deployment Guide

TL;DR:
- `inference_service` provides pluggable `/ocr` and `/risk` endpoints (reference + optional real providers).
- Keep CI lightweight: optional OCR/depth dependencies are split into extra requirements files.
- For replay/report/regression usage, read `Gateway/README.md`.

## Common Commands (PowerShell)

```powershell
cd Gateway
python -m pip install -r requirements.txt
python -m uvicorn services.inference_service.app:app --host 127.0.0.1 --port 19120
```

ONNX depth optional:

```powershell
python -m pip install -r services/inference_service/requirements-onnx-depth.txt
python services/inference_service/tools/verify_depth_onnx.py --path D:\models\depth_anything_v2_small\model.onnx --expected-sha256 <sha256>
```

## API Contract

- `POST /ocr` -> `{"text": "...", "latencyMs": <int>, "model": "<id>"}`
- `POST /risk` -> `{"hazards": [...], "latencyMs": <int>, "model": "<id>"}`

## Provider Matrix

| Domain | Provider | Env Value | Optional Dependency |
|---|---|---|---|
| OCR | reference | `BYES_SERVICE_OCR_PROVIDER=reference` | none |
| OCR | tesseract | `BYES_SERVICE_OCR_PROVIDER=tesseract` | `requirements-tesseract.txt` |
| OCR | paddleocr | `BYES_SERVICE_OCR_PROVIDER=paddleocr` | `requirements-paddleocr.txt` |
| Risk | reference | `BYES_SERVICE_RISK_PROVIDER=reference` | none |
| Risk | heuristic | `BYES_SERVICE_RISK_PROVIDER=heuristic` | `requirements-heuristic-risk.txt` |
| Depth (for heuristic risk) | none/synth/midas/onnx | `BYES_SERVICE_DEPTH_PROVIDER=<...>` | midas/onnx are optional |

## Calibrated Risk Defaults (v4.28 -> v4.29)

Current default thresholds:
- `depthObsCrit = 0.55` (`BYES_RISK_DEPTH_OBS_CRIT`)
- `depthDropoffDelta = 0.4` (`BYES_RISK_DEPTH_DROPOFF_DELTA`)
- `obsCrit = 0.28` (`BYES_RISK_OBS_CRIT`)

All defaults remain env-overridable.

## ONNX Depth Quick Setup (Optional)

### 1) Install optional runtime

```powershell
python -m pip install -r services/inference_service/requirements-onnx-depth.txt
```

### 2) Prepare model (outside repo)

- Source: `onnx-community/depth-anything-v2-small -> onnx/model.onnx`
- Example path: `D:\models\depth_anything_v2_small\model.onnx`

### 3) Verify model file

```powershell
python services/inference_service/tools/verify_depth_onnx.py --path D:\models\depth_anything_v2_small\model.onnx --expected-sha256 <sha256_from_hf_page>
```

### 4) Run service with ONNX depth

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

Recommended default input size is `256` (can test `384`/`518` with sweep tools).

## Core Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `BYES_SERVICE_OCR_PROVIDER` | `reference` | OCR provider selection |
| `BYES_SERVICE_RISK_PROVIDER` | `reference` | risk provider selection |
| `BYES_SERVICE_DEPTH_PROVIDER` | `none` | depth provider for heuristic risk |
| `BYES_SERVICE_OCR_MODEL_ID` | provider default | OCR model metadata tag |
| `BYES_SERVICE_RISK_MODEL_ID` | provider default | risk model metadata tag |
| `BYES_SERVICE_DEPTH_MODEL_ID` | provider default | depth model metadata tag |
| `BYES_SERVICE_DEPTH_ONNX_PATH` | empty | ONNX depth model path (`onnx` provider) |
| `BYES_SERVICE_DEPTH_INPUT_SIZE` | `256` | ONNX depth input resolution |
| `BYES_SERVICE_RISK_DEBUG` | `0` | include `debug` evidence in `/risk` |

## Connect With Gateway

```powershell
cd Gateway
$env:BYES_RISK_BACKEND="http"
$env:BYES_RISK_HTTP_URL="http://127.0.0.1:19120/risk"
$env:BYES_OCR_BACKEND="http"
$env:BYES_OCR_HTTP_URL="http://127.0.0.1:19120/ocr"
$env:BYES_INFERENCE_EMIT_WS_V1="1"
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_risk_gt_min --reset
```

Then inspect:
- `events/events_v1.jsonl` for backend/model/endpoint/latency evidence.
- `report.json` for `inference` summary and quality metrics.

## References

- Gateway runtime + evaluation flow: `Gateway/README.md`
- Root overview: `README.md`
- Event schema: `docs/event_schema_v1.md`
- Hazard taxonomy: `docs/hazard_taxonomy_v1.md`
