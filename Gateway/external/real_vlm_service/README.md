# RealVLM Service (Stub)

## Run local

```bash
cd Gateway/external/real_vlm_service
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 9103
```

## Docker

```bash
docker build -t byes-real-vlm .
docker run --rm -p 9103:9103 byes-real-vlm
```

## Env knobs

- `VLM_SLEEP_MS`: fixed latency simulation (default `140`)
- `VLM_FAIL_PROB`: random failure probability `0..1` (default `0`)
