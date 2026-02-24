# BYES Event Schema v1

`schemaVersion`: `byes.event.v1`

## Fields
- `tsMs`: event timestamp in ms.
- `runId`: optional run id.
- `frameSeq`: optional frame sequence id.
- `component`: `unity|gateway|cloud|sim|unknown`.
- `category`: `tool|safety|system|scenario|metric|ui|unknown`.
- `name`: normalized event name (`ocr.read`, `risk.hazards`, `safety.confirm`, etc.).
- `phase`: optional lifecycle stage (`start|result|error|info`).
- `status`: optional normalized status (`ok|timeout|cancel|error`).
- `latencyMs`: optional latency in ms.
- `payload`: normalized payload object.
  - recommended tool metadata keys inside payload:
    - `backend`: `mock|http|local`
    - `model`: model identifier (optional)
    - `endpoint`: sanitized endpoint URL/path (optional)
- `raw`: optional raw event (debug use only).

## Name Catalog (up to v4.82)
- `ocr.read`
- `risk.hazards`
- `safety.confirm`
- `safety.latch`
- `safety.preempt`
- `safety.local_fallback`
- `pov.ingest`
- `pov.context`
- `plan.request`
- `plan.generate`
- `plan.execute`
- `plan.rule_applied`
- `plan.context_alignment`
- `plan.context_pack`
- `map.costmap`
- `map.costmap_context`
- `map.costmap_fused`
- `seg.segment`
- `seg.prompt`
- `depth.estimate`
- `slam.pose`
- `frame.input`
- `frame.ack`
- `frame.e2e`
- `frame.user_e2e`
- `ui.command`
- `ui.confirm_request`
- `ui.confirm_response`

## UI Payload Recommendations
- `ui.command` payload:
  - `commandType`: `speak|overlay|haptic|stop`
  - `actionId`: stable action id
  - `text`: optional speech text
  - `label`: optional overlay label
  - `reason`: optional reason tag
- `ui.confirm_request` payload:
  - `confirmId`
  - `text`
  - `timeoutMs`
- `ui.confirm_response` payload:
  - `confirmId`
  - `accepted`: bool
  - `latencyMs`: optional (derived from request/response delta when available)

## Examples

### 1) OCR intent (start)
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000000120,
  "frameSeq": 1,
  "component": "gateway",
  "category": "tool",
  "name": "ocr.read",
  "phase": "start",
  "status": "ok",
  "latencyMs": null,
  "payload": {"requestId": "ocr-1"}
}
```

### 2) OCR result (text)
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000000180,
  "frameSeq": 1,
  "component": "gateway",
  "category": "tool",
  "name": "ocr.read",
  "phase": "result",
  "status": "ok",
  "latencyMs": 110,
  "payload": {
    "schemaVersion": "byes.ocr.v1",
    "lines": [{"text": "EXIT", "score": 0.99, "bbox": [10, 20, 80, 60]}],
    "linesCount": 1,
    "backend": "http",
    "model": "reference-ocr-v1",
    "endpoint": "http://127.0.0.1:19120/ocr"
  }
}
```

### 3) Risk hazards result
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000000900,
  "frameSeq": 1,
  "component": "gateway",
  "category": "tool",
  "name": "risk.hazards",
  "phase": "result",
  "status": "ok",
  "latencyMs": 88,
  "payload": {"hazards": [{"hazardKind": "stair_down", "severity": "critical"}], "backend": "http", "model": "depth-anything-v2-small", "endpoint": "http://127.0.0.1:9002/risk"}
}
```

### 4) Safety confirm timeout / latch
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000000600,
  "frameSeq": 1,
  "component": "gateway",
  "category": "safety",
  "name": "safety.confirm",
  "phase": "error",
  "status": "timeout",
  "latencyMs": null,
  "payload": {"reason": "timeout", "requestId": "conf-1"}
}
```

```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000000820,
  "frameSeq": 1,
  "component": "gateway",
  "category": "safety",
  "name": "safety.latch",
  "phase": "info",
  "status": "ok",
  "latencyMs": 300,
  "payload": {"reason": "critical_latch"}
}
```

### 5) Depth estimate result
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000000950,
  "frameSeq": 1,
  "component": "gateway",
  "category": "tool",
  "name": "depth.estimate",
  "phase": "result",
  "status": "ok",
  "latencyMs": 42,
  "payload": {
    "backend": "http",
    "model": "reference-depth-v1",
    "endpoint": "http://127.0.0.1:19241/depth",
    "meta": {
      "provider": "da3",
      "refViewStrategy": "auto_ref",
      "poseUsed": false,
      "warningsCount": 0
    },
    "grid": {
      "format": "grid_u16_mm_v1",
      "size": [16, 16],
      "unit": "mm",
      "values": [1000, 1002, 1004]
    },
    "gridCount": 1,
    "valuesCount": 256
  }
}
```

### 6) SLAM pose result
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000001010,
  "frameSeq": 2,
  "component": "gateway",
  "category": "tool",
  "name": "slam.pose",
  "phase": "result",
  "status": "ok",
  "latencyMs": 36,
  "payload": {
    "schemaVersion": "byes.slam_pose.v1",
    "backend": "http",
    "model": "reference-slam-v1",
    "endpoint": "http://127.0.0.1:19261/slam/pose",
    "trackingState": "tracking",
    "pose": {
      "t": [0.1, 0.0, 0.0],
      "q": [0.0, 0.0, 0.0, 1.0],
      "frame": "world_to_cam"
    },
    "warningsCount": 0
  }
}
```

`v4.82` note:
- `payload.meta.refViewStrategy` is optional and used for temporal-consistency analysis/reporting.
- Single-frame depth metrics (`absRel`, `rmse`, `delta1`) remain unchanged.
- Temporal metrics are report-level aggregates from consecutive `depth.estimate` events (`quality.depthTemporal`), not new event names.
