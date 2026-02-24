# 架构总览

## 一句话总结

Unity（或回放夹具）将帧发送到 Gateway；Gateway 调用可插拔推理后端，产出标准化 `events_v1`，随后由报告/排行榜/回归流程消费这些产物，用于可复现的安全评估。

## 端到端数据流

```text
Unity / RunPackage replay
        |
        v
Gateway (/api/frame, scheduler, fusion, safety)
        |
        +--> 推理后端: mock 或 http
                 |
                 v
        inference_service (/ocr, /risk, /depth, /seg, /slam/pose)
                 |
                 v
events/events_v1.jsonl  + metrics_before/after
        |
        v
report_run.py -> report.json + report.md
        |
        +--> /api/run_packages + /runs 排行榜
        |
        +--> run_regression_suite.py + CI gate
```

## 核心组件

- `Gateway/main.py`
  - 运行时 API、RunPackage 导入、排行榜 API/页面。
- `Gateway/byes/*`
  - 调度、安全内核、指标、推理后端适配器。
- `Gateway/services/inference_service/*`
  - OCR/risk 提供方选择，以及可选 ONNX 深度推理。
- `Gateway/scripts/*`
  - 回放/报告/回归/扫参/标定工具链。

## 事件契约

主要产物：
- `events/events_v1.jsonl`

典型风险结果事件包含：
- `category=tool`, `name=risk.hazards`, `phase=result`, `status=ok`
- `event.latencyMs`（权威延迟值）
- `payload.backend`, `payload.model`, `payload.endpoint`
- 可选 `payload.debug`（深度/时序/阈值证据）

## 质量与安全闭环

1. 回放夹具/RunPackage。
2. 生成报告（`report.json`）。
3. 重点查看：
   - `quality.depthRisk.critical.missCriticalCount`
   - `quality.riskLatencyMs`
   - `quality.qualityScoreBreakdown`
4. 在回归套件中与基线比较。
5. CI 在以下情况失败：
   - 质量下降超出阈值
   - 违反 critical FN 硬门禁（`missCriticalCount > 0`）。

## 这对评审为何重要

- 可复现：同一夹具 -> 同一报告/门禁结果。
- 可解释：事件级证据 + 报告级汇总。
- 安全优先演进：标定与硬门禁可避免静默回归。

## v4.82 深度时序一致性闭环

`v4.82` 在不改变单帧深度质量指标的前提下，新增时序一致性评测链路：

1. `da3_depth_service` 支持可选 `refViewStrategy` 与 `pose` 输入。
2. `inference_service` 将 `refViewStrategy` 透传到 DA3 下游（`reference|da3`）。
3. Gateway 在 `depth.estimate` 事件中保留 `payload.meta`：
   - `provider`
   - `refViewStrategy`
   - `poseUsed`
4. `report_run.py` 基于相邻深度帧计算 `quality.depthTemporal`：
   - `jitterAbs`（`p50/p90/max`）
   - `flickerRateNear`（`mean/p90/max`）
   - `scaleDriftProxy`（`p90/max`）
   - `refViewStrategyDiversityCount`
5. 排行榜与矩阵汇总新增时序列，支持 profile 对比。

这使深度“时间稳定性”可量化、可回归、可解释。
