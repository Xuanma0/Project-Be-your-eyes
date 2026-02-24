# SAM3 Segmentation Service

Fixture-first segmentation service for a SAM3-compatible HTTP endpoint.

v4.65 goals:
- keep CI deterministic with `fixture` mode;
- provide `sam3` mode plumbing for local real-model integration;
- keep response shape compatible with `byes.seg.v1`.

## Run

```powershell
cd Gateway/services/sam3_seg_service
python -m pip install -r requirements.txt
python -m uvicorn services.sam3_seg_service.app:app --app-dir ../../ --host 127.0.0.1 --port 19271
```

## Environment

- `BYES_SAM3_MODE=fixture|sam3` (default: `fixture`)
- `BYES_SAM3_FIXTURE_DIR=<run_package_dir>` (uses `<dir>/gt/seg_gt_v1.json`)
- `BYES_SAM3_FIXTURE_PATH=<path/to/seg_gt_v1.json>` (optional direct file path)
- `BYES_SAM3_RUN_ID=<run_id>` (default: `fixture-seg-gt`, used when fixture json does not contain `runId`)
- `BYES_SAM3_MODEL_ID=sam3-v1`
- `BYES_SAM3_CKPT_PATH=<path/to/sam3_checkpoint>` (required only in `sam3` mode)
- `BYES_SAM3_DEVICE=cpu|cuda` (default: `cpu`)
- `BYES_SAM3_TIMEOUT_MS=2000`
- `BYES_SAM3_ENDPOINT=<echo_endpoint>` (optional response override)

## API

- `GET /healthz`
  - reports mode, fixture source, runIds, and sam3 readiness diagnostics.

- `POST /seg`
  - request:
    - `runId`, `frameSeq`
    - optional `image_b64`
    - optional `targets`
    - optional `tracking` (`true` enables video-tracking mode when backend supports it)
    - optional `prompt` (`targets/text/boxes/points/meta.promptVersion`)
    - optional `mode` per-request override (`fixture|sam3`)
  - response (`byes.seg.v1` compatible):
    - `segments`: list of `{label, score, bbox, trackId?, trackState?, mask?}`
    - `segmentsCount`
    - `backend="sam3"`
    - `model=<BYES_SAM3_MODEL_ID>`
    - `endpoint`
    - optional `warningsCount`

## Behavior notes

- `fixture` mode:
  - deterministic lookup by `(runId, frameSeq)` from fixture GT.
  - missing run/frame returns `segments=[]` plus warning (no 500).
  - if fixture rows include `mask` (`rle_v1`) and/or `trackId/trackState`, fields are returned unchanged.

- `sam3` mode:
  - if checkpoint path is missing/invalid, `/seg` returns HTTP 500 with readable `sam3_not_ready:*`.
  - v4.65 keeps inference as a stub (empty segments) but healthz clearly exposes readiness.
  - tracking behavior is backend-dependent; v4.80 wires request/response fields and keeps fixture mode deterministic for CI.
  - model weights are external assets and must not be committed to this repository.
