# 术语表

## RunPackage

包含帧、元数据、事件及指标输入/输出的可回放数据包，可用于确定性的离线评估。

## events_v1

标准化事件流文件，位于 `events/events_v1.jsonl`。工具结果（OCR/risk）使用稳定 schema，并包含权威 `event.latencyMs`。

## qualityScore

`report.json` 中的综合质量指标（`quality.qualityScore`），按 OCR/risk/安全行为组件提供分解。

## Critical FN（关键假阴性）

与真值相比漏检关键风险。在报告中字段为：`quality.depthRisk.critical.missCriticalCount`。

## 排行榜（Leaderboard）

Run 列表 API/页面（`/api/run_packages`、`/runs`），汇总质量、延迟、确认行为与关键漏检。

## Regression Gate

`run_regression_suite.py` 与 CI 中的自动通过/失败检查：
- 质量下降门禁，
- critical FN 硬门禁（受门禁 run 的 `missCriticalCount` 必须保持为 `0`）。

## 推理后端（Inference Backend）

Gateway 侧 OCR/risk 后端模式（`mock` 或 `http`），用于获取模型推理结果。

## inference_service 提供方（Provider）

服务侧通过环境变量选择的实现：
- OCR 提供方（`reference`、`tesseract`、`paddleocr`）
- risk 提供方（`reference`、`heuristic`）
- depth 提供方（`none`、`synth`、`midas`、`onnx`）

## Latch / Preempt / Fallback

报告中汇总的安全行为信号：
- latch：保持安全状态行为；
- preempt：在完整计划完成前提前干预；
- fallback：降级的本地兜底动作。

## Sweep

输入尺寸扫参（`sweep_depth_input_size.py`），用于量化 ONNX 深度的速度/质量权衡。

## Calibration

阈值网格搜索（`calibrate_risk_thresholds.py`），用于降低 FP 并强制 `critical FN == 0`，同时输出漏检解释报告。

## 深度时序指标（Depth Temporal）

基于相邻深度帧的报告级一致性指标：
- `jitterAbs`：ROI 内帧间深度绝对变化量。
- `flickerRateNear`：近距离掩码在相邻帧的异或比例。
- `scaleDriftProxy`：ROI 中位深度的帧间漂移。

## Ref View Strategy

DA3 的参考视角策略提示（例如 `auto_ref`、`first`、`middle`），通过 `depth.estimate.payload.meta.refViewStrategy` 透传和审计。

## Plan Request v1

结构化规划请求契约（`byes.plan_request.v1`），可携带 risk/seg/pov/slam/costmap 的上下文片段与元信息。

## Context Pack（上下文包）

由结构化上下文信号生成的“预算化文本 + 统计”对象：
- `seg.context.v1`
- `slam.context.v1`
- `plan.context_pack.v1`
- `costmap.context.v1`

## Costmap / Costmap Fused

- `byes.costmap.v1`：由 depth/seg/slam 生成的单帧局部代价栅格。
- `byes.costmap_fused.v1`：带 EMA/可选位姿 shift 的时序融合代价图，并附稳定性统计。

## Matrix Profile

`run_dataset_benchmark.py` 中的命名实验配置（services/env/prehooks），用于多 profile 横向对比。

## Prehook

在 benchmark matrix 中，每个 run package 报告前的预处理步骤（例如 `pyslam_ingest` / `pyslam_run`）。
