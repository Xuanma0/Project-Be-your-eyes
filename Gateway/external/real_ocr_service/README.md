# RealOCR External Service

Minimal HTTP OCR service used by `Gateway` `real_ocr` tool.

## Run (local)

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 9102
```

## Run (docker)

```bash
docker build -t byes-real-ocr .
docker run --rm -p 9102:9102 byes-real-ocr
```

## API

- `POST /infer/ocr` (multipart form)
  - field: `image` (jpg/png bytes)
  - response:
    - `lines`: array of `{text, score, box}`
    - `summary`: compact textual summary
    - `latencyMs`: service-side elapsed time

## Dev Fault Controls

- `OCR_SLEEP_MS` (default `80`)
  - Adds fixed delay before returning OCR output.
- `OCR_TIMEOUT_PROB` (default `0`)
  - Probability in `[0,1]` that request hangs for 30s.
  - Use to verify Gateway timeout + SAFE_MODE behavior.
