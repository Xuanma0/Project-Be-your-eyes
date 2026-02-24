# Reference Depth Service

Deterministic fixture-backed depth service for HTTP integration tests and local demos.

## Run

```powershell
cd Gateway/services/reference_depth_service
python -m pip install -r requirements.txt
python -m uvicorn services.reference_depth_service.app:app --app-dir ../../ --host 127.0.0.1 --port 19241
```

## Environment

- `BYES_REF_DEPTH_FIXTURE_DIR`: run package directory containing `gt/depth_gt_v1.json` (preferred)
- `BYES_REF_DEPTH_FIXTURE_PATH`: explicit path to depth GT json
- `BYES_REF_DEPTH_RUN_ID`: expected run id key (default: `fixture-depth-gt`)
- `BYES_REF_DEPTH_ENDPOINT`: optional endpoint string echoed in response

## API

- `POST /depth`
  - request: `{ "runId":"...", "frameSeq":1, "image_b64":"..." }`
  - response (`byes.depth.v1` compatible):
    - `grid`: `{format:"grid_u16_mm_v1", size:[gw,gh], unit:"mm", values:[...]}`
    - `gridCount` / `valuesCount`
    - `backend="reference"`
    - `model="reference-depth-v1"`
    - `endpoint`
    - optional `warning` when run/frame is missing

