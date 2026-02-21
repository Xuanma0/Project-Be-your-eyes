# Reference OCR Service

Deterministic fixture-backed OCR service for HTTP integration tests and local demos.

## Run

```powershell
cd Gateway/services/reference_ocr_service
python -m pip install -r requirements.txt
python -m uvicorn services.reference_ocr_service.app:app --app-dir ../../ --host 127.0.0.1 --port 19251
```

## Environment

- `BYES_REF_OCR_FIXTURE_DIR`: run package directory containing `gt/ocr_gt_v1.json` (preferred)
- `BYES_REF_OCR_FIXTURE_PATH`: explicit path to OCR GT json
- `BYES_REF_OCR_RUN_ID`: expected run id key (default: `fixture-ocr-gt`)
- `BYES_REF_OCR_ENDPOINT`: optional endpoint string echoed in response

## API

- `POST /ocr`
  - request: `{ "runId":"...", "frameSeq":1, "image_b64":"..." }`
  - response (`byes.ocr.v1` compatible):
    - `lines`: `[{text, score?, bbox?}]`
    - `linesCount`
    - `backend="reference"`
    - `model="reference-ocr-v1"`
    - `endpoint`
    - optional `warning` when run/frame is missing

## Gateway HTTP Chain Example

```powershell
# terminal 1: reference OCR
python -m uvicorn services.reference_ocr_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19251

# terminal 2: inference_service -> reference OCR
$env:BYES_SERVICE_OCR_PROVIDER="http"
$env:BYES_SERVICE_OCR_ENDPOINT="http://127.0.0.1:19251/ocr"
python -m uvicorn services.inference_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19120

# terminal 3: Gateway replay with OCR
cd Gateway
$env:BYES_ENABLE_OCR="1"
$env:BYES_OCR_BACKEND="http"
$env:BYES_OCR_HTTP_URL="http://127.0.0.1:19120/ocr"
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_ocr_gt_min --reset
```

