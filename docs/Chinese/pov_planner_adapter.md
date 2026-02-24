# POV 规划器适配器 v1

本文档定义了从 `pov.ir.v1` 到 `byes.action_plan.v1` 的确定性适配器。

## 范围

- 提供方（Provider）：`Gateway/services/planner_service` 中的 `BYES_PLANNER_PROVIDER=pov`。
- 输入：
  - 首选：规划器请求体内联 `povIr` 对象；
  - 兼容方式：`runPackagePath` 指向包含 `pov/pov_ir_v1.json` 的回放包。
- 输出：由 `validate_action_plan.py` 严格校验的 `byes.action_plan.v1`。

## 映射规则（MVP）

1. Decisions -> actions：
- Decision 文本包含 stop/critical/danger/hazard：生成 `stop`（blocking）。
- Decision 文本包含 confirm/wait/clarify/ask：生成 `confirm`（blocking）。

2. Highlights -> speak：
- 最多合并前两条 highlight 文本。
- 生成 `speak` action，`payload.source="pov"`。
- 通过将 highlight 的 `tMs` 匹配到 decision 时间窗（`t0Ms..t1Ms`）来填充 `payload.sourceDecisionIds`；若匹配不到，取最近的先前 decision。

3. 风险等级：
- 任一 critical 风格 decision/event -> `riskLevel=critical`。
- 否则若有 warning/high 信号 -> `riskLevel=medium`。
- 否则 `riskLevel=low`。

4. 动作约束：
- 使用 `constraints.maxActions` 对 actions 做校验和裁剪。
- 按 `priority` 保持确定性顺序。

## 回退（Fallback）

当 `pov/pov_ir_v1.json` 缺失或无效时：
- 回退到 reference 规划器，
- 设置规划器元数据：
  - `fallbackUsed=true`
  - `fallbackReason=missing_pov_ir` 或 `pov_adapter_error`
  - `jsonValid=false`

## 在线摄入流程

1. 在 Gateway 上通过 `POST /api/pov/ingest` 提交完整 `pov.ir.v1` 负载。
2. Gateway 将每个 `runId` 的最新 POV 保存到内存（`PovStore`）。
3. `POST /api/plan?provider=pov` 可将内联 `povIr` 转发给规划器服务。
4. 产生事件：
   - `pov.ingest`
   - `plan.generate`
   - `safety.kernel`

## 对齐指标

`report.json.povPlan` 提供适配器消费证据：
- `decisionCoverage`
- `actionCoverage`
- `consistencyWarnings`
- `warnings`

契约夹具：`Gateway/tests/fixtures/pov_plan_min`。
