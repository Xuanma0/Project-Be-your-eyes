# RealDepth Mock Service

## Run

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8012
```

## Docker

```bash
docker build -t byes-real-depth .
docker run --rm -p 8012:8012 byes-real-depth
```

## Dev Knobs

- `DELAY_MS`: artificial inference latency (default `120`)
- `FAIL_PROB`: hang probability to trigger gateway timeout (default `0`)
- `DEPTH_PRIMARY_KIND`: override primary hazard kind (default `obstacle`)
- `DEPTH_MODEL`: override returned model name (default `mock_depth_v1`)
