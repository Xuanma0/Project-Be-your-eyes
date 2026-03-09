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
- `det.objects`
- `det.objects.v1`
- `vis.overlay.v1`
- `seg.mask.v1`
- `depth.map.v1`
- `asr.transcript.v1`
- `assist.trigger`
- `target.session`
- `target.update`
- `depth.estimate`
- `risk.fused`
- `slam.pose`
- `slam.pose.v1`
- `slam.trajectory.v1`
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
- `frame.ack` payload:
  - `schemaVersion`: `frame.ack.v1`
  - `kind`: `tts|overlay|haptic|any`
  - optional `provider` object for evidence (`backend/model/device/reason/isMock`)

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

### 6) Detection objects result
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000000990,
  "frameSeq": 1,
  "component": "gateway",
  "category": "tool",
  "name": "det.objects",
  "phase": "result",
  "status": "ok",
  "latencyMs": 55,
  "payload": {
    "schemaVersion": "byes.det.v1",
    "backend": "http",
    "model": "yolo11n",
    "endpoint": "http://127.0.0.1:19120/det",
    "objects": [
      {
        "label": "person",
        "conf": 0.91,
        "box_xyxy": [120, 80, 380, 620],
        "mask": {
          "format": "polygon_v1",
          "points": [[120, 80], [380, 80], [380, 620], [120, 620]]
        }
      }
    ],
    "objectsCount": 1,
    "topK": 5,
    "openVocab": true,
    "promptUsed": ["door", "exit sign"]
  }
}
```

### 6.4) Detection objects v1 (HUD-friendly)
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000001050,
  "frameSeq": 1,
  "component": "gateway",
  "category": "tool",
  "name": "det.objects.v1",
  "phase": "result",
  "status": "ok",
  "latencyMs": 57,
  "payload": {
    "schemaVersion": "byes.det.v1",
    "objectsCount": 1,
    "imageWidth": 960,
    "imageHeight": 540,
    "objects": [
      {
        "label": "door",
        "conf": 0.88,
        "trackId": "17",
        "box_xyxy": [220, 90, 480, 510],
        "box_norm": [0.229, 0.167, 0.5, 0.944]
      }
    ]
  }
}
```

### 6.1) Assist trigger event
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000001000,
  "frameSeq": 18,
  "component": "gateway",
  "category": "ui",
  "name": "assist.trigger",
  "phase": "result",
  "status": "ok",
  "payload": {
    "schemaVersion": "byes.assist_request.v1",
    "deviceId": "quest3-device",
    "action": "find",
    "targets": ["det"],
    "maxAgeMs": 1500,
    "cacheAgeMs": 221,
    "prompt": {"text": "exit sign", "openVocab": true, "task": "find"}
  }
}
```

### 6.2) Target session lifecycle event
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000001012,
  "frameSeq": 18,
  "component": "gateway",
  "category": "tool",
  "name": "target.session",
  "phase": "result",
  "status": "ok",
  "payload": {
    "schemaVersion": "byes.target.session.v1",
    "sessionId": "trk_quest3_a1b2c3d4",
    "deviceId": "quest3-device",
    "runId": "quest3-smoke",
    "status": "active",
    "tracker": "botsort",
    "roi": {"x": 0.35, "y": 0.35, "w": 0.3, "h": 0.3},
    "prompt": "door",
    "seg": {"enabled": true, "mode": "sam3"},
    "createdTsMs": 1704000001000,
    "updatedTsMs": 1704000001012
  }
}
```

### 6.3) Target update event
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000001110,
  "frameSeq": 19,
  "component": "gateway",
  "category": "tool",
  "name": "target.update",
  "phase": "result",
  "status": "ok",
  "payload": {
    "schemaVersion": "byes.target.update.v1",
    "sessionId": "trk_quest3_a1b2c3d4",
    "deviceId": "quest3-device",
    "runId": "quest3-smoke",
    "step": 19,
    "tracker": "botsort",
    "roi": {"x": 0.35, "y": 0.35, "w": 0.3, "h": 0.3},
    "prompt": "door",
    "target": {
      "label": "door",
      "conf": 0.87,
      "boxNorm": [0.41, 0.29, 0.58, 0.86],
      "boxXyxy": [320, 160, 540, 900]
    },
    "hasDetection": true,
    "seg": {
      "enabled": true,
      "mode": "sam3",
      "payloadPresent": true
    },
    "updatedTsMs": 1704000001110
  }
}
```

### 6.4) Segmentation mask asset event (`seg.mask.v1`)
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000001120,
  "frameSeq": 19,
  "component": "gateway",
  "category": "tool",
  "name": "seg.mask.v1",
  "phase": "result",
  "status": "ok",
  "payload": {
    "schemaVersion": "byes.seg.mask.v1",
    "assetId": "a_1704000001120_5f0c9a31",
    "w": 960,
    "h": 540,
    "label": "door",
    "trackId": "17",
    "roi": {"x0": 0.23, "y0": 0.17, "x1": 0.50, "y1": 0.94}
  }
}
```

### 6.5) Depth colormap asset event (`depth.map.v1`)
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000001140,
  "frameSeq": 19,
  "component": "gateway",
  "category": "tool",
  "name": "depth.map.v1",
  "phase": "result",
  "status": "ok",
  "payload": {
    "schemaVersion": "byes.depth.map.v1",
    "assetId": "a_1704000001140_b839d12e",
    "w": 160,
    "h": 120,
    "minDepthM": 0.74,
    "maxDepthM": 4.91
  }
}
```

### 6.6) Overlay companion event (`vis.overlay.v1`)
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000001150,
  "frameSeq": 19,
  "component": "gateway",
  "category": "tool",
  "name": "vis.overlay.v1",
  "phase": "result",
  "status": "ok",
  "payload": {
    "schemaVersion": "byes.vis.overlay.v1",
    "kind": "det",
    "assetId": "a_1704000001150_overlay_det",
    "w": 960,
    "h": 540,
    "inferMs": 28,
    "providerMeta": {
      "backend": "ultralytics",
      "model": "yolo26n.pt",
      "endpoint": "http://127.0.0.1:19120/det"
    },
    "tsMs": 1704000001150
  }
}
```

### 6.7) ASR transcript event (`asr.transcript.v1`)
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000001200,
  "frameSeq": 22,
  "component": "gateway",
  "category": "tool",
  "name": "asr.transcript.v1",
  "phase": "result",
  "status": "ok",
  "payload": {
    "schemaVersion": "byes.asr.transcript.v1",
    "deviceId": "quest3-device",
    "runId": "quest3-smoke",
    "frameSeq": 22,
    "text": "read this",
    "language": "auto",
    "backend": "mock",
    "model": "mock-asr-v1",
    "latencyMs": 4
  }
}
```

### 7) Fused risk from depth grid
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000001010,
  "frameSeq": 1,
  "component": "gateway",
  "category": "tool",
  "name": "risk.fused",
  "phase": "result",
  "status": "ok",
  "latencyMs": 0,
  "payload": {
    "available": true,
    "min_depth_m": 0.78,
    "left_min_m": 1.02,
    "center_min_m": 0.78,
    "right_min_m": 0.95,
    "suggested_dir": "left",
    "unit": "m"
  }
}
```

### 8) SLAM pose result (`slam.pose` / `slam.pose.v1`)
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

`slam.pose.v1` emits a normalized payload for HUD/runtime consumers:
```json
{
  "schemaVersion": "byes.event.v1",
  "name": "slam.pose.v1",
  "payload": {
    "schemaVersion": "byes.slam.pose.v1",
    "trackingState": "tracking",
    "pose": {
      "t": [0.1, 0.0, 0.0],
      "q": [0.0, 0.0, 0.0, 1.0],
      "frame": "world_to_cam"
    },
    "backend": "http",
    "model": "reference-slam-v1",
    "endpoint": "http://127.0.0.1:19261/slam/pose"
  }
}
```

`slam.trajectory.v1` (low frequency) provides recent pose history:
```json
{
  "schemaVersion": "byes.event.v1",
  "name": "slam.trajectory.v1",
  "payload": {
    "schemaVersion": "byes.slam.trajectory.v1",
    "deviceId": "quest3-device",
    "trackingState": "tracking",
    "points": [
      {"tsMs": 1704000001000, "t": [0.0, 0.0, 0.0], "q": [0.0, 0.0, 0.0, 1.0], "trackingState": "tracking"},
      {"tsMs": 1704000002000, "t": [0.1, 0.0, 0.0], "q": [0.0, 0.0, 0.0, 1.0], "trackingState": "tracking"}
    ]
  }
}
```

`v4.82` note:
- `payload.meta.refViewStrategy` is optional and used for temporal-consistency analysis/reporting.
- Single-frame depth metrics (`absRel`, `rmse`, `delta1`) remain unchanged.
- Temporal metrics are report-level aggregates from consecutive `depth.estimate` events (`quality.depthTemporal`), not new event names.

`v5.03` note:
- `seg.masks` payload remains optional even when segmentation is requested.
- A normalized mask object, when present, should follow one of:
  - `{"format":"rle_v1","size":[h,w],"counts":[...]}` (preferred for transport),
  - `{"format":"polygon_v1","points":[[x,y],...]}` (lightweight overlay use),
  - `{"format":"png_b64","size":[h,w],"data":"..."}` (fallback/debug).

`v5.04` note:
- `seg.mask.v1` and `depth.map.v1` move heavy visualization payloads to `/api/assets/{assetId}` and keep WS event payloads lightweight.
- Recording run packages persist referenced assets under `assets/` and keep `events/events_v1.jsonl` as asset-id references (no large inline base64).

`v5.05` note:
- `vis.overlay.v1` is a lightweight companion signal for Quest/Desktop renderers; binary payloads remain in `/api/assets/{assetId}`.

