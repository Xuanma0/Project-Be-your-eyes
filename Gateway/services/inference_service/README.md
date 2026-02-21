# Inference Service Deployment Guide

TL;DR:
- `inference_service` provides pluggable `/ocr`, `/risk`, `/seg`, and `/depth` endpoints.
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

- `POST /ocr` -> `{"schemaVersion":"byes.ocr.v1","runId":"...","frameSeq":1,"lines":[{"text":"...","score":0.9,"bbox":[x0,y0,x1,y1]}],"linesCount":1,"latencyMs":<int>,"backend":"...","model":"...","endpoint":"...","warningsCount":0}`
- `POST /risk` -> `{"hazards": [...], "latencyMs": <int>, "model": "<id>"}`
- `POST /seg` -> `{"segments": [{"label":"...","score":0.0,"bbox":[x0,y0,x1,y1],"mask?":{"format":"rle_v1","size":[H,W],"counts":[...]}}], "latencyMs": <int>, "model": "<id>"}`
  - request supports optional:
    - `targets: string[]`
    - `prompt: {"schemaVersion":"byes.seg_request.v1","targets":[...],"text":"...","boxes":[...],"points":[...],"meta":{"promptVersion":"v1"}}`
- `POST /depth` -> `{"grid":{"format":"grid_u16_mm_v1","size":[gw,gh],"unit":"mm","values":[...]}, "gridCount": <int>, "valuesCount": <int>, "latencyMs": <int>, "model": "<id>" }`
  - request supports optional:
    - `runId: string`
    - `frameSeq: int`
    - `targets: string[]` (reserved for future providers)

## Provider Matrix

| Domain | Provider | Env Value | Optional Dependency |
|---|---|---|---|
| OCR | mock | `BYES_SERVICE_OCR_PROVIDER=mock` | none |
| OCR | http | `BYES_SERVICE_OCR_PROVIDER=http` | none (calls external endpoint) |
| OCR | reference | `BYES_SERVICE_OCR_PROVIDER=reference` | none |
| OCR | tesseract | `BYES_SERVICE_OCR_PROVIDER=tesseract` | `requirements-tesseract.txt` |
| OCR | paddleocr | `BYES_SERVICE_OCR_PROVIDER=paddleocr` | `requirements-paddleocr.txt` |
| Risk | reference | `BYES_SERVICE_RISK_PROVIDER=reference` | none |
| Risk | heuristic | `BYES_SERVICE_RISK_PROVIDER=heuristic` | `requirements-heuristic-risk.txt` |
| Seg | mock | `BYES_SERVICE_SEG_PROVIDER=mock` | none |
| Seg | http | `BYES_SERVICE_SEG_PROVIDER=http` | none (calls external endpoint) |
| Depth tool (`/depth`) | mock | `BYES_SERVICE_DEPTH_PROVIDER=mock` | none |
| Depth tool (`/depth`) | http | `BYES_SERVICE_DEPTH_PROVIDER=http` | none (calls external endpoint) |
| Depth (for heuristic risk) | none/synth/midas/onnx | `BYES_SERVICE_DEPTH_PROVIDER=<...>` | midas/onnx are optional |

## Seg Provider (mock/http)

- `mock` (default): returns deterministic empty segments for contract/testing paths.
- `http`: forwards image to external segmentation endpoint and normalizes output.
- Response shape must stay stable for Gateway metrics:
  - `segments`: list of `{label, score, bbox:[x0,y0,x1,y1], mask?}`
  - `latencyMs`: service-side latency
  - `model`: provider/model id tag
- Optional request field:
  - `targets`: list of labels (for downstream provider filtering/prompting)
  - `prompt`: rich prompt object for future SAM2/SAM3 adapters (forwarded to HTTP provider and may condition output if downstream supports prompt filtering)
  - Gateway v4.51 sends packed prompt budgets by default; see Gateway env:
    - `BYES_SEG_PROMPT_MAX_CHARS`
    - `BYES_SEG_PROMPT_MAX_TARGETS`
    - `BYES_SEG_PROMPT_MAX_BOXES`
    - `BYES_SEG_PROMPT_MAX_POINTS`
    - `BYES_SEG_PROMPT_BUDGET_MODE`
- Optional response metadata:
  - `targetsCount`, `targetsUsed`
- If downstream returns `mask` (`rle_v1`), `http` provider keeps it and passes through to Gateway events/report.
- Gateway records `seg.segment` events and computes `quality.seg` (`IoU/F1@0.5/coverage/latency`) during `report_run`.

Required env for `http`:

```powershell
$env:BYES_SERVICE_SEG_PROVIDER="http"
$env:BYES_SERVICE_SEG_ENDPOINT="http://127.0.0.1:19120/seg"
```

Optional:

```powershell
$env:BYES_SERVICE_SEG_MODEL_ID="sam3-seg-v1"
$env:BYES_SERVICE_SEG_TIMEOUT_MS="1200"
```

Reference seg chain example:

```powershell
# start reference seg service first
python -m uvicorn services.reference_seg_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19231

# then start inference_service with seg provider=http
$env:BYES_SERVICE_SEG_PROVIDER="http"
$env:BYES_SERVICE_SEG_ENDPOINT="http://127.0.0.1:19231/seg"
$env:BYES_SERVICE_SEG_MODEL_ID="reference-seg-v1"
python -m uvicorn services.inference_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19120
```

## OCR Provider (mock/http)

- `mock` (default): returns deterministic OCR lines for contract/testing paths.
- `http`: forwards image to external OCR endpoint and normalizes `byes.ocr.v1` response fields.

Required env for `http`:

```powershell
$env:BYES_SERVICE_OCR_PROVIDER="http"
$env:BYES_SERVICE_OCR_ENDPOINT="http://127.0.0.1:19251/ocr"
```

Optional:

```powershell
$env:BYES_SERVICE_OCR_MODEL_ID="reference-ocr-v1"
$env:BYES_SERVICE_OCR_TIMEOUT_MS="1200"
```

Reference OCR chain example:

```powershell
# start reference ocr service first
python -m uvicorn services.reference_ocr_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19251

# then start inference_service with ocr provider=http
$env:BYES_SERVICE_OCR_PROVIDER="http"
$env:BYES_SERVICE_OCR_ENDPOINT="http://127.0.0.1:19251/ocr"
$env:BYES_SERVICE_OCR_MODEL_ID="reference-ocr-v1"
python -m uvicorn services.inference_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19120
```

## Depth Tool Provider (mock/http)

- `mock` (default for `/depth`): returns deterministic low-resolution depth grid.
- `http`: forwards image to external depth endpoint and normalizes output.
- Response shape for Gateway metrics/events:
  - `grid`: `{format:"grid_u16_mm_v1", size:[gw,gh], unit:"mm", values:[0..65535]}`
  - `gridCount`, `valuesCount`
  - `latencyMs`, `model`, `backend`, `endpoint`

Required env for `http`:

```powershell
$env:BYES_SERVICE_DEPTH_PROVIDER="http"
$env:BYES_SERVICE_DEPTH_ENDPOINT="http://127.0.0.1:19241/depth"
```

Optional:

```powershell
$env:BYES_SERVICE_DEPTH_MODEL_ID="reference-depth-v1"
$env:BYES_SERVICE_DEPTH_TIMEOUT_MS="1200"
```

Reference depth chain example:

```powershell
# start reference depth service first
python -m uvicorn services.reference_depth_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19241

# then start inference_service with depth provider=http
$env:BYES_SERVICE_DEPTH_PROVIDER="http"
$env:BYES_SERVICE_DEPTH_ENDPOINT="http://127.0.0.1:19241/depth"
$env:BYES_SERVICE_DEPTH_MODEL_ID="reference-depth-v1"
python -m uvicorn services.inference_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19120
```

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
| `BYES_SERVICE_OCR_PROVIDER` | `mock` | OCR provider selection |
| `BYES_SERVICE_RISK_PROVIDER` | `reference` | risk provider selection |
| `BYES_SERVICE_SEG_PROVIDER` | `mock` | segmentation provider selection (`mock|http`) |
| `BYES_SERVICE_DEPTH_PROVIDER` | `none` | depth provider for heuristic risk |
| `BYES_SERVICE_OCR_MODEL_ID` | provider default | OCR model metadata tag |
| `BYES_SERVICE_RISK_MODEL_ID` | provider default | risk model metadata tag |
| `BYES_SERVICE_SEG_MODEL_ID` | provider default | seg model metadata tag |
| `BYES_SERVICE_SEG_ENDPOINT` | empty | seg endpoint URL (`http` provider) |
| `BYES_SERVICE_SEG_TIMEOUT_MS` | `1200` | seg HTTP timeout ms |
| `BYES_SERVICE_DEPTH_MODEL_ID` | provider default | depth model metadata tag |
| `BYES_SERVICE_DEPTH_ENDPOINT` | empty | depth endpoint URL (`http` provider for `/depth`) |
| `BYES_SERVICE_DEPTH_TIMEOUT_MS` | `1200` | depth HTTP timeout ms (`/depth`) |
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
