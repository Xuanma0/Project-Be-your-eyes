# DA3 Depth Service

Fixture-first depth service for a DA3-compatible HTTP endpoint.

v4.66 goals:
- keep CI deterministic with `fixture` mode;
- provide `da3` mode plumbing for local real-model integration;
- keep response shape compatible with `byes.depth.v1`.

## Run

```powershell
cd Gateway/services/da3_depth_service
python -m pip install -r requirements.txt
python -m uvicorn services.da3_depth_service.app:app --app-dir ../../ --host 127.0.0.1 --port 19281
```

## Environment

- `BYES_DA3_MODE=fixture|da3` (default: `fixture`)
- `BYES_DA3_FIXTURE_DIR=<run_package_dir>` (uses `<dir>/gt/depth_gt_v1.json`)
- `BYES_DA3_FIXTURE_PATH=<path/to/depth_gt_v1.json>` (optional direct file path)
- `BYES_DA3_RUN_ID=<run_id>` (default: `fixture-da3-depth`)
- `BYES_DA3_MODEL_ID=da3-v1`
- `BYES_DA3_MODEL_PATH=<path/to/da3_model>` (required only in `da3` mode)
- `BYES_DA3_DEVICE=cpu|cuda` (default: `cpu`)
- `BYES_DA3_TIMEOUT_MS=2000`
- `BYES_DA3_ENDPOINT=<echo_endpoint>` (optional response override)

## API

- `GET /healthz`
  - reports mode, fixture source, runIds, model path and da3 readiness diagnostics.

- `POST /depth`
  - request:
    - `runId`, `frameSeq`
    - optional `image_b64`
    - optional `mode` per-request override (`fixture|da3`)
    - optional `refViewStrategy` (e.g. `auto_ref|first|middle`)
    - optional `pose` object (v4.82 hook; fixture mode only records `poseUsed`)
  - response (`byes.depth.v1` compatible):
    - `grid`: `{format:"grid_u16_mm_v1", size:[gw,gh], unit:"mm", values:[...]}`
    - `gridCount`, `valuesCount`
    - `backend="da3"`
    - `model=<BYES_DA3_MODEL_ID>`
    - `endpoint`
    - optional `meta`: `{provider, refViewStrategy, poseUsed, warningsCount}`
    - optional `warningsCount`

## Behavior notes

- `fixture` mode:
  - deterministic lookup by `(runId, frameSeq)` from fixture GT.
  - missing run/frame returns `gridCount=0` plus warning (no 500).

- `da3` mode:
  - if model path is missing/invalid, `/depth` returns HTTP 500 with readable `da3_not_ready:*`.
  - v4.66 keeps inference as a lightweight stub grid (no heavy model dependency in CI).
  - v4.82 forwards `refViewStrategy` into response `meta` (and into future DA3 pipeline hooks).
  - model files are external assets and must not be committed to this repository.
