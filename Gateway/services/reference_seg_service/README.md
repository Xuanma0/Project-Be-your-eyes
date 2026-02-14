# Reference Segmentation Service

Deterministic fixture-backed segmentation service for HTTP integration tests and local demos.

## Run

```powershell
cd Gateway/services/reference_seg_service
python -m pip install -r requirements.txt
python -m uvicorn services.reference_seg_service.app:app --app-dir ../../ --host 127.0.0.1 --port 19231
```

## Environment

- `BYES_REF_SEG_FIXTURE_PATH`: path to seg GT fixture json (default: `Gateway/tests/fixtures/run_package_with_seg_gt_min/gt/seg_gt_v1.json`)
- `BYES_REF_SEG_RUN_ID`: expected run id key (default: `fixture-seg-gt`)
- `BYES_REF_SEG_ENDPOINT`: optional endpoint string echoed in response

## API

- `POST /seg`
  - request: `{ "runId": "...", "frameSeq": 1, "image_b64": "..." }`
  - response (byes.seg.v1 compatible):
    - `segments`: `[{label, score, bbox}]`
    - `segmentsCount`
    - `backend="reference"`
    - `model="reference-seg-v1"`
    - `endpoint`
    - optional `warning` when run/frame is missing

