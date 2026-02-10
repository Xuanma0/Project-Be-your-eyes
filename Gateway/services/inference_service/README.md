# Inference Service (Reference + Optional Real OCR Providers)

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

## D) Connect Gateway + replay

```bash
set BYES_OCR_BACKEND=http
set BYES_OCR_HTTP_URL=http://127.0.0.1:19101/ocr
set BYES_OCR_MODEL_ID=<same as service model>
set BYES_RISK_BACKEND=http
set BYES_RISK_HTTP_URL=http://127.0.0.1:19101/risk
set BYES_RISK_MODEL_ID=reference-risk-v1
python Gateway/scripts/dev_replay_with_http_ocr.py --run-package Gateway/tests/fixtures/run_package_with_gt_min --ocr-url http://127.0.0.1:19101/ocr --risk-url http://127.0.0.1:19101/risk
```

Check outputs:
- `events/events_v1.jsonl`: `event.latencyMs` set, payload has `backend/model/endpoint`, no `payload.latencyMs`
- `report.json`: top-level `inference` block records OCR/Risk backend/model/endpoint
