# Reference SLAM Service

Deterministic fixture-backed SLAM pose service for HTTP integration tests and local demos.

## Run

```powershell
cd Gateway/services/reference_slam_service
python -m pip install -r requirements.txt
python -m uvicorn services.reference_slam_service.app:app --app-dir ../../ --host 127.0.0.1 --port 19261
```

## Environment

- `BYES_REF_SLAM_FIXTURE_DIR`: run package directory containing `gt/slam_pose_gt_v1.json` (preferred)
- `BYES_REF_SLAM_FIXTURE_PATH`: explicit path to SLAM GT json
- `BYES_REF_SLAM_RUN_ID`: expected run id key (default: `fixture-slam-gt`)
- `BYES_REF_SLAM_ENDPOINT`: optional endpoint string echoed in response

## API

- `POST /slam/pose`
  - request: `{ "runId":"...", "frameSeq":1, "image_b64":"..." }`
  - response (`byes.slam_pose.v1` compatible):
    - `trackingState`: `tracking|lost|relocalized|initializing|unknown`
    - `pose`: `{t:[tx,ty,tz], q:[qx,qy,qz,qw], frame?, mapId?, cov?}`
    - `backend="reference"`
    - `model="reference-slam-v1"`
    - `endpoint`
    - optional `warning` when run/frame is missing

