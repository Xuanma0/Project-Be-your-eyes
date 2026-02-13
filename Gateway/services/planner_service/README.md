# Planner Service

Deterministic planner HTTP service for Gateway `BYES_PLANNER_BACKEND=http`.

## TL;DR
- Default provider is `reference` (no model download, deterministic).
- Optional provider `llm` supports generic HTTP/OpenAI-compatible endpoints.
- LLM outputs are strictly validated as `byes.action_plan.v1`; invalid output auto-falls back to reference planner.

## Run

```powershell
cd Gateway/services/planner_service
python -m pip install -r requirements.txt
python app.py
```

Default endpoint: `http://127.0.0.1:19211/plan`

## Providers

### Reference (default)

```powershell
set BYES_PLANNER_PROVIDER=reference
```

Behavior:
- critical hazard -> `confirm + speak` (no stop; Gateway SafetyKernel injects stop)
- warning/high -> `speak + overlay`
- no hazards -> `speak`

### LLM Adapter (optional)

```powershell
set BYES_PLANNER_PROVIDER=llm
set BYES_PLANNER_LLM_ENDPOINT=http://127.0.0.1:8088/generate
set BYES_PLANNER_LLM_TIMEOUT_MS=2500
set BYES_PLANNER_PROMPT_VERSION=v1
```

Optional OpenAI-compatible mode (still via HTTP, no SDK dependency):

```powershell
set BYES_PLANNER_LLM_MODE=openai
set BYES_PLANNER_LLM_ENDPOINT=https://api.openai.com/v1/chat/completions
set BYES_PLANNER_LLM_API_KEY=<key>
set BYES_PLANNER_LLM_MODEL=gpt-4o-mini
```

Generic HTTP LLM stub example (returns `{ "text": "<ActionPlan JSON string>" }`):

```powershell
@'
from flask import Flask, jsonify, request
app = Flask(__name__)
@app.post("/generate")
def gen():
    _ = request.get_json(silent=True) or {}
    return jsonify({"text": "{\"schemaVersion\":\"byes.action_plan.v1\",\"runId\":\"stub\",\"frameSeq\":1,\"generatedAtMs\":0,\"intent\":\"assist\",\"riskLevel\":\"low\",\"ttlMs\":2000,\"actions\":[{\"type\":\"speak\",\"priority\":0,\"payload\":{\"text\":\"stub\"},\"requiresConfirm\":false,\"blocking\":false}],\"meta\":{\"planner\":{\"backend\":\"http\",\"model\":\"stub-llm\",\"endpoint\":null},\"budget\":{\"contextMaxTokensApprox\":0,\"contextMaxChars\":0,\"mode\":\"decisions_plus_highlights\"},\"safety\":{\"guardrailsApplied\":[]}}}"})
app.run("127.0.0.1", 8088)
'@ | python -
```

### Prompt templates

- `prompts/planner_system.md`
- `prompts/planner_user.md`

`promptVersion` is propagated into plan metadata for reproducibility.

## API

- `POST /plan`
  - input: `byes.planner_request.v1`
  - output: `byes.action_plan.v1`

On LLM failures (`timeout`, `http_error`, `invalid_json`, `schema_error`), the response still returns 200 with a reference plan and metadata:
- `meta.planner.fallbackUsed=true`
- `meta.planner.fallbackReason=<reason>`
- `meta.planner.jsonValid=false`
