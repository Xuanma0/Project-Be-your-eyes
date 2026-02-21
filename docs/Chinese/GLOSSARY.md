# 术语表

## RunPackage

包含帧、元数据、事件及指标输入/输出的可回放数据包，可用于确定性的离线评估。

## events_v1

标准化事件流文件，位于 `events/events_v1.jsonl`。工具结果（OCR/risk）使用稳定 schema，并包含权威 `event.latencyMs`。

## qualityScore

`report.json` 中的综合质量指标（`quality.qualityScore`），按 OCR/risk/安全行为组件提供分解。

## Critical FN（关键假阴性）

与真值相比漏检关键风险。在报告中字段为：`quality.depthRisk.critical.missCriticalCount`。

## Leaderboard

Run 列表 API/页面（`/api/run_packages`、`/runs`），汇总质量、延迟、确认行为与关键漏检。

## Regression Gate

`run_regression_suite.py` 与 CI 中的自动通过/失败检查：
- 质量下降门禁，
- critical FN 硬门禁（受门禁 run 的 `missCriticalCount` 必须保持为 `0`）。

## Inference Backend

Gateway 侧 OCR/risk 后端模式（`mock` 或 `http`），用于获取模型推理结果。

## inference_service Provider

服务侧通过环境变量选择的实现：
- OCR provider（`reference`、`tesseract`、`paddleocr`）
- risk provider（`reference`、`heuristic`）
- depth provider（`none`、`synth`、`midas`、`onnx`）

## Latch / Preempt / Fallback

报告中汇总的安全行为信号：
- latch：保持安全状态行为；
- preempt：在完整计划完成前提前干预；
- fallback：降级的本地兜底动作。

## Sweep

输入尺寸扫参（`sweep_depth_input_size.py`），用于量化 ONNX 深度的速度/质量权衡。

## Calibration

阈值网格搜索（`calibrate_risk_thresholds.py`），用于降低 FP 并强制 `critical FN == 0`，同时输出漏检解释报告。
