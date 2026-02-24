# BYES Event Schema v1

`schemaVersion`: `byes.event.v1`

## 字段
- `tsMs`：事件时间戳（毫秒）。
- `runId`：可选 run id。
- `frameSeq`：可选帧序号。
- `component`：`unity|gateway|cloud|sim|unknown`。
- `category`：`tool|safety|system|scenario|metric|ui|unknown`。
- `name`：标准化事件名（`ocr.scan_text`、`risk.hazards`、`safety.confirm` 等）。
- `phase`：可选生命周期阶段（`start|result|error|info`）。
- `status`：可选标准化状态（`ok|timeout|cancel|error`）。
- `latencyMs`：可选延迟（毫秒）。
- `payload`：标准化负载对象。
  - 建议在 payload 内提供工具元数据键：
    - `backend`：`mock|http|local`
    - `model`：模型标识（可选）
    - `endpoint`：脱敏后的 endpoint URL/path（可选）
- `raw`：可选原始事件（仅用于调试）。

## 名称目录（含 v4.35 新增）
- `ocr.scan_text`
- `risk.hazards`
- `safety.confirm`
- `safety.latch`
- `safety.preempt`
- `safety.local_fallback`
- `plan.generate`
- `plan.execute`
- `seg.segment`
- `depth.estimate`
- `ui.command`
- `ui.confirm_request`
- `ui.confirm_response`

## UI 负载建议
- `ui.command` 的 payload：
  - `commandType`：`speak|overlay|haptic|stop`
  - `actionId`：稳定 action id
  - `text`：可选语音文本
  - `label`：可选叠加层标签
  - `reason`：可选原因标签
- `ui.confirm_request` 的 payload：
  - `confirmId`
  - `text`
  - `timeoutMs`
- `ui.confirm_response` 的 payload：
  - `confirmId`
  - `accepted`：布尔值
  - `latencyMs`：可选（可由 request/response 时间差推导）

## 示例

### 1) OCR 意图（start）
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000000120,
  "frameSeq": 1,
  "component": "gateway",
  "category": "tool",
  "name": "ocr.scan_text",
  "phase": "start",
  "status": "ok",
  "latencyMs": null,
  "payload": {"requestId": "ocr-1"}
}
```

### 2) OCR 结果（text）
```json
{
  "schemaVersion": "byes.event.v1",
  "tsMs": 1704000000180,
  "frameSeq": 1,
  "component": "gateway",
  "category": "tool",
  "name": "ocr.scan_text",
  "phase": "result",
  "status": "ok",
  "latencyMs": 110,
  "payload": {"text": "EXIT", "backend": "http", "model": "paddleocr-v4", "endpoint": "http://127.0.0.1:9001/ocr"}
}
```

### 3) 风险 hazards 结果
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

### 4) 安全确认超时 / latch
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

### 5) 深度估计结果
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
