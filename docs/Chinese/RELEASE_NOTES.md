Current development version is defined by `VERSION`; this file records historical milestones only.

# 版本发布记录（v4.x）

本文档按版本总结 `v4.38` 到 `v4.82` 的核心能力闭环，便于评审与维护。

## v4.38
- 规划评测指标、ablation 扫参（`provider/prompt/budget`）、排行榜/报告接入、回归门禁。

## v4.39-v4.40
- POV 规划适配器（`pov.ir.v1 -> action_plan.v1`）。
- 在线 POV ingest API + 内存存储 + inline `povIr` 规划链路。

## v4.41
- 契约冻结机制（`Gateway/contracts/*` + `contract.lock.json`）。
- `/api/contracts` 与 suite/CI 严格契约校验。

## v4.42-v4.44
- 分割 provider 链路（`mock/http`）与 `/seg`。
- 分割质量指标 + GT fixture。
- `byes.seg.v1` 冻结与 payload 归一化校验。

## v4.45-v4.47
- `reference_seg_service` 与 HTTP E2E。
- 分割提示契约（`byes.seg_request.v1`）+ prompt 透传 + `seg.prompt` 事件。

## v4.48-v4.50
- `byes.seg.v1` 可选 mask（`rle_v1`）与 mask 质量指标。
- prompt-conditioned 分割行为与 prompt+mask 契约覆盖。

## v4.51-v4.52
- 分割提示预算/截断工程化。
- Seg ContextPack（`seg.context.v1`）+ `/api/seg/context` + planner prompt v2 可选拼接。

## v4.53-v4.55
- `byes.plan_request.v1` + 上下文感知 planner HTTP 请求。
- 可解释 seg-hint 规则层。
- plan-context 对齐指标（`plan.context_alignment.v1`）。
- 统一 PlanContextPack（`plan.context_pack.v1`）+ `/api/plan/context`。

## v4.56-v4.58
- 单请求 plan context pack override。
- context sweep 工具。
- 帧级 E2E 延迟契约/事件（`frame.e2e.v1`）与唯一性/一致性加固。

## v4.59-v4.60
- `frame.input.v1` + `frame.ack.v1` + capture->feedback user-E2E 指标。
- 按 kind（`tts/ar/haptic`）分桶的 user-E2E 报告/排行榜。

## v4.61-v4.64
- 深度能力链路（`byes.depth.v1`、reference depth service、质量评测）。
- 模型资产清单（`byes.models.v1`、`/api/models`、`verify_models.py`）。
- OCR 能力链路（`byes.ocr.v1`、reference OCR、CER/完全匹配指标）。
- SLAM pose 能力链路（`byes.slam_pose.v1`、reference SLAM、稳定性指标）。

## v4.65-v4.66
- `sam3_seg_service`（fixture/sam3）与下游切换。
- `da3_depth_service`（fixture/da3）与下游切换。
- SAM3/DA3 模型文件要求纳入模型清单校验。

## v4.67-v4.75
- pySLAM TUM 轨迹注入为离线 `slam.pose` 事件。
- 数据集导入器（Ego4D 视频 / 图片目录）与 benchmark 批跑 + matrix profiles。
- pySLAM prehook（`pyslam_ingest`、`pyslam_run`）。
- SLAM 轨迹误差指标（`ATE/RPE`）。
- SlamContextPack（`slam.context.v1`）+ `/api/slam/context`。

## v4.76-v4.79
- 将 SLAM context 接入 plan_request 与 planner prompt（`v3`）。
- Local costmap（`byes.costmap.v1`）+ costmap context（`costmap.context.v1`）+ planner prompt（`v4`）。
- Fused costmap（`byes.costmap_fused.v1`，EMA/可选 shift）。
- Shift gate（可解释 reject 原因）与 online/final 轨迹 profile 对比。

## v4.80-v4.81
- SAM3 tracking 透传（`trackId`、`trackState`）与 segTracking 指标。
- 基于 trackId 的动态障碍时序缓存，接入 costmap/costmap_fused。

## v4.82
- DA3 `refViewStrategy` 端到端透传。
- 深度时序一致性指标：
  - `jitterAbs`
  - `flickerRateNear`
  - `scaleDriftProxy`
  - `refViewStrategyDiversityCount`
- 接入 report/leaderboard/linter/contract gate/matrix summary。
