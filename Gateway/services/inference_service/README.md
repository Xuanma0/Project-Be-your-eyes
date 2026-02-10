# Inference Service (Reference + Optional Real OCR/Risk Providers)

This service is optional and isolated from `Gateway/requirements.txt` so CI stays lightweight.

API contract stays fixed:

- `POST /ocr` => `{"text": "...", "latencyMs": <int>, "model": "<id>"}`
- `POST /risk` => `{"hazards": [...], "latencyMs": <int>, "model": "<id>"}`

## A) Reference provider (default)

```bash
cd Gateway/services/inference_service
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
set BYES_SERVICE_OCR_PROVIDER=reference
python scripts/run_service.py --port 19101
```

## B) Tesseract provider (optional)

1) Install system Tesseract binary first.
2) Install Python deps:

```bash
pip install -r requirements-tesseract.txt
```

3) Run:

```bash
set BYES_SERVICE_OCR_PROVIDER=tesseract
set BYES_SERVICE_OCR_MODEL_ID=tesseract-v5
set BYES_TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe
python scripts/run_service.py --port 19101
```

## C) PaddleOCR provider (optional)

```bash
pip install -r requirements-paddleocr.txt
set BYES_SERVICE_OCR_PROVIDER=paddleocr
set BYES_SERVICE_OCR_MODEL_ID=paddleocr-v4-en
python scripts/run_service.py --port 19101
```

Notes:
- first run may download model assets depending on paddle settings.
- use CPU package variants if needed for your platform.

## D) Heuristic Risk provider (optional lightweight)

```bash
pip install -r requirements-heuristic-risk.txt
set BYES_SERVICE_RISK_PROVIDER=heuristic
set BYES_SERVICE_RISK_MODEL_ID=heuristic-risk-v1
python scripts/run_service.py --port 19101
```

Optional thresholds:
- `BYES_RISK_OBS_WARN`
- `BYES_RISK_OBS_CRIT`
- `BYES_RISK_DROPOFF_PEAK`
- `BYES_RISK_DROPOFF_CONTRAST`
- `BYES_RISK_UNKNOWN_BRIGHTNESS`  (format: `low,high`, default `32,222`)
- `BYES_RISK_DEPTH_ENABLE` (`1|0`, default `1`)
- `BYES_RISK_DEPTH_OBS_WARN` (default `1.0`)
- `BYES_RISK_DEPTH_OBS_CRIT` (default `0.6`)
- `BYES_RISK_DEPTH_DROPOFF_DELTA` (default `0.8`)

Heuristic output uses canonical hazard taxonomy (`dropoff`, `stair_down`, `obstacle_close`, `unknown_depth`) and avoids emitting `dropoff` + `stair_down` together for the same frame.

## E) Depth provider for risk (optional)

Depth providers are selected independently and consumed by the heuristic risk provider.

Defaults:
- `BYES_SERVICE_DEPTH_PROVIDER=none`

Test/CI-friendly option:
```bash
set BYES_SERVICE_DEPTH_PROVIDER=synth
```

Real-model option (optional, local-only):
```bash
pip install -r requirements-depth-midas-onnx.txt
set BYES_SERVICE_DEPTH_PROVIDER=midas
set BYES_SERVICE_DEPTH_MODEL_PATH=C:\\models\\midas_small.onnx
set BYES_SERVICE_DEPTH_MODEL_ID=midas-small-onnx
```

When enabled, `/risk` can emit depth-backed evidence in hazards and optional debug payload.

## F) /risk debug evidence toggle

Enable lightweight debug evidence in `/risk` response:
```bash
set BYES_SERVICE_RISK_DEBUG=1
```
`debug` includes depth provider stats and active thresholds. Default is `0` (disabled).

## G) Connect Gateway + replay

```bash
set BYES_OCR_BACKEND=http
set BYES_OCR_HTTP_URL=http://127.0.0.1:19101/ocr
set BYES_OCR_MODEL_ID=<same as service model>
set BYES_RISK_BACKEND=http
set BYES_RISK_HTTP_URL=http://127.0.0.1:19101/risk
set BYES_RISK_MODEL_ID=heuristic-risk-v1
python Gateway/scripts/dev_replay_with_http_ocr.py --run-package Gateway/tests/fixtures/run_package_with_gt_min --ocr-url http://127.0.0.1:19101/ocr --risk-url http://127.0.0.1:19101/risk
```

Check outputs:
- `events/events_v1.jsonl`: `event.latencyMs` set, payload has `backend/model/endpoint`, no `payload.latencyMs`
- `risk.hazards` payload entries include `hazardKind`, `severity`, and optional `score/evidence`
- `report.json`: top-level `inference` block records OCR/Risk backend/model/endpoint
