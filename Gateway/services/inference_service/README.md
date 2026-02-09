# Reference Inference Service (Optional)

This service is a lightweight template for real OCR + risk model serving.
It is **not** required by CI and is intentionally isolated from `Gateway/requirements.txt`.

## Start

```bash
cd Gateway/services/inference_service
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 9001
```

Endpoints:

- `POST /ocr`
  - input: `{"image_b64":"...","frameSeq":1}`
  - output: `{"text":"EXIT","latencyMs":123,"model":"reference-ocr-v1"}`
- `POST /risk`
  - input: `{"image_b64":"...","frameSeq":1}`
  - output: `{"hazards":[{"hazardKind":"stair_down","severity":"warning"}],"latencyMs":88,"model":"reference-risk-v1"}`

## Connect Gateway

```bash
set BYES_OCR_BACKEND=http
set BYES_OCR_HTTP_URL=http://127.0.0.1:9001/ocr
set BYES_OCR_MODEL_ID=reference-ocr-v1
set BYES_RISK_BACKEND=http
set BYES_RISK_HTTP_URL=http://127.0.0.1:9001/risk
set BYES_RISK_MODEL_ID=reference-risk-v1
```

Then run replay or live frame upload and inspect:

- `events/events_v1.jsonl` (`payload.backend/model/endpoint`, `event.latencyMs`)
- `report.json` top-level `inference` block

## Notes

- This implementation returns deterministic placeholder outputs.
- Replace internals in `app.py` with real model code as needed.
