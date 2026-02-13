# Reference Planner Service

Deterministic HTTP planner service used by Gateway when `BYES_PLANNER_BACKEND=http`.

## Run

```powershell
cd Gateway/services/planner_service
python -m pip install -r requirements.txt
python app.py
```

Default endpoint: `http://127.0.0.1:19211/plan`

## API

- `POST /plan`
  - input: `byes.planner_request.v1`
  - output: `byes.action_plan.v1`

Behavior:
- critical hazard -> `confirm + speak` (no stop; SafetyKernel in Gateway injects stop)
- warning/high -> `speak + overlay`
- no hazards -> `speak`
