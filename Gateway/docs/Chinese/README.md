# Gateway 开发与评估指南

[English Version](../../README.md)

TL;DR：
- `Gateway` 是运行时中枢：接收帧/事件，调用推理后端，并输出标准化事件。
- 它支持“回放优先”的评估链路：`RunPackage -> events_v1 -> report.json -> leaderboard -> regression gate`。
- 推理服务部署细节请阅读 `Gateway/services/inference_service/README.md`。
- 全版本里程碑请阅读 `docs/Chinese/RELEASE_NOTES.md`（英文见 `docs/English/RELEASE_NOTES.md`）。

术语约定（本文统一使用）：
- 回放包：`RunPackage`
- 上下文包：`context pack`
- 规划器：`planner`
- 提示词：`prompt`
- 提供方：`provider`

## 环境准备（PowerShell，必需）

方案 A：`venv`

```powershell
cd Gateway
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

方案 B：conda

```powershell
cd Gateway
conda create -n byes python=3.11 -y
conda activate byes
python -m pip install -U pip
python -m pip install -r requirements.txt
```

## 常用命令（PowerShell）

```powershell
cd Gateway
python -m pytest -q
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_risk_gt_min --reset
python scripts/report_run.py --run-package tests/fixtures/run_package_with_risk_gt_min
python scripts/run_regression_suite.py --suite regression/suites/baseline_suite.json --baseline regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
```

## Gateway 的作用

- 接收 Unity/客户端输入并编排工具与后端调用。
- 记录/标准化事件（`events/events_v1.jsonl`），用于确定性分析。
- 从回放或在线产物生成质量报告（`report.json` + markdown）。
- 提供运行排行榜 API 与看板页面（`/api/run_packages`、`/runs`）。
- 在 CI 中执行回归阈值门禁（包含 `critical FN == 0`）。

## 评估工作流

### 1) 回放回放包（RunPackage）

```powershell
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_risk_gt_min --reset
```

### 2) 生成报告

```powershell
python scripts/report_run.py --run-package tests/fixtures/run_package_with_risk_gt_min
```

### 3) 检查关键文件

- `events/events_v1.jsonl`：权威事件延迟（`event.latencyMs`）与工具元数据。
- `report.json`：推理摘要、OCR/risk 质量、安全行为与评分拆解。

### 4) 与基线套件对比

```powershell
python scripts/run_regression_suite.py --suite regression/suites/baseline_suite.json --baseline regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
```

门禁重点：
- 评分下降门禁（`--fail-on-drop`）
- 关键安全门禁（`--fail-on-critical-fn`，默认开启）
- 当 `report.quality.depthRisk.critical.missCriticalCount > 0` 时判定本次回放失败

## POV 契约（POV-compiler -> BYES）

- 契约 schema 的唯一事实来源：`../schemas/pov_ir_v1.schema.json`
- 将一个 POV IR 导入回放包：

```powershell
python scripts/ingest_pov_ir.py --run-package <run_package_dir> --pov-ir <pov_ir.json> --strict 1
```

- 契约回归套件：

```powershell
python scripts/run_regression_suite.py --suite regression/suites/contract_suite.json --baseline regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
```

## POV 上下文 API

从 POV IR 构建受预算控制的上下文包：

```powershell
curl -X POST "http://127.0.0.1:8000/api/pov/context" `
  -H "Content-Type: application/json" `
  -d '{"runPackage":"Gateway/tests/fixtures/pov_ir_v1_min","budget":{"maxChars":2000,"maxTokensApprox":500},"mode":"decisions_plus_highlights"}'
```

请求参数：
- `mode`：`decisions_only` | `decisions_plus_highlights` | `full`
- `budget.maxChars`：提示词字符上限
- `budget.maxTokensApprox`：近似 token 上限（`ceil(chars/4)`）

审计输出：
- `events/events_v1.jsonl`：追加 `pov.context` 事件，包含输出/截断统计。
- `report.json`：查看 `povContext` 的默认预算输出统计与截断情况。

## v4.82：DA3 深度时序一致性（新增）

本版本新增深度时序稳定性评测闭环，并已接入报告/排行榜/matrix：

- `depth.estimate` 事件支持可选 `payload.meta`：
  - `provider`
  - `refViewStrategy`
  - `poseUsed`
- `report.json -> quality.depthTemporal`：
  - `jitterAbs`（帧间深度抖动）
  - `flickerRateNear`（近距离区域闪烁率）
  - `scaleDriftProxy`（尺度漂移代理）
  - `refViewStrategyDiversityCount`

常用命令：

```powershell
python scripts/report_run.py --run-package tests/fixtures/run_package_with_depth_temporal_min
python scripts/run_regression_suite.py --suite regression/suites/contract_suite.json --baseline regression/baselines/baseline.json --fail-on-drop
python scripts/run_dataset_benchmark.py --root artifacts/imports/v468_ego4d_demo --out artifacts/benchmarks/v482_demo --matrix 1 --profiles scripts/profiles/v482_depth_temporal_profiles.json --replay 0 --shuffle 0 --max 10
```

## 分割（mock/http）

在 Gateway 启用分割事件输出：

```powershell
cd Gateway
$env:BYES_ENABLE_SEG="1"
$env:BYES_SEG_BACKEND="mock"   # 或 http
$env:BYES_SEG_MODEL_ID="mock-seg-v1"
# 可选开放词表 targets：
# $env:BYES_SEG_TARGETS="person,car,stairs"
# $env:BYES_SEG_TARGETS_JSON='["person","car","stairs"]'
# 可选分割提示词（JSON 优先级高于 TEXT）：
# $env:BYES_SEG_PROMPT_TEXT="find stairs and handrail"
# $env:BYES_SEG_PROMPT_JSON='{"schemaVersion":"byes.seg_request.v1","targets":["stairs"],"text":"find stairs and handrail","meta":{"promptVersion":"v1"}}'
# 可选分割提示词预算（v4.51）：
# $env:BYES_SEG_PROMPT_MAX_CHARS="256"
# $env:BYES_SEG_PROMPT_MAX_TARGETS="8"
# $env:BYES_SEG_PROMPT_MAX_BOXES="4"
# $env:BYES_SEG_PROMPT_MAX_POINTS="8"
# $env:BYES_SEG_PROMPT_BUDGET_MODE="targets_text_boxes_points"
# 使用 http 后端时：
# $env:BYES_SEG_HTTP_URL="http://127.0.0.1:19120/seg"
```

期望证据：
- `events/events_v1.jsonl` 包含 `name="seg.segment"`，payload 中有 `segmentsCount`、`backend`、`model`、`endpoint`。
- `report.json` 包含从 `events_v1` 推断的 `inference.seg`。

分割质量评估（bbox IoU/F1/coverage/latency）：

```powershell
python scripts/report_run.py --run-package tests/fixtures/run_package_with_seg_gt_min
python scripts/run_regression_suite.py --suite regression/suites/seg_suite.json --baseline regression/baselines/baseline.json --fail-on-drop
```

`report.json -> quality.seg` 字段：
- `framesTotal / framesWithGt / framesWithPred / coverage`
- `precision / recall / f1At50 / meanIoU`
- `latencyMs`（`p50/p90/max`）
- `topMisses / topFP`（调试样本）

排行榜字段：
- 列：`seg_f1_50`、`seg_coverage`、`seg_latency_p90`
- 过滤：`min_seg_f1_50`、`min_seg_coverage`、`max_seg_latency_p90`
- 排序：`sort=seg_f1_50|seg_coverage|seg_latency_p90`

未来 SAM3 路径：
- 保持 `BYES_SEG_BACKEND=http`；
- 将 `BYES_SEG_HTTP_URL` 指向外部兼容 SAM3 的 `POST /seg` 服务；
- 返回 `segments` 结构为 `{label, score, bbox}`。
- 可选 `targets` 提示词透传已端到端打通（`BYES_SEG_TARGETS` / `BYES_SEG_TARGETS_JSON`）。
- 支持富提示词透传（`BYES_SEG_PROMPT_TEXT` / `BYES_SEG_PROMPT_JSON`），并记录为 `seg.prompt` 事件。
- 内置提示词预算打包器；`seg.prompt` / `report.segPrompt` 包含 `budget`、`out`、`truncation`、`complexity`、`truncationRate`。

参考 seg HTTP 链路（Gateway -> inference_service -> reference_seg_service）：

```powershell
# 终端 1：reference seg service
python -m uvicorn services.reference_seg_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19231

# 终端 2：inference_service（seg provider=http -> reference seg service）
$env:BYES_SERVICE_SEG_PROVIDER="http"
$env:BYES_SERVICE_SEG_ENDPOINT="http://127.0.0.1:19231/seg"
python -m uvicorn services.inference_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19120

# 终端 3：Gateway 回放（启用 seg）
cd Gateway
$env:BYES_ENABLE_SEG="1"
$env:BYES_SEG_BACKEND="http"
$env:BYES_SEG_HTTP_URL="http://127.0.0.1:19120/seg"
$env:BYES_SEG_TARGETS="person,chair"  # 匹配 run_package_with_seg_gt_min 夹具标签
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_seg_gt_min --reset
python scripts/report_run.py --run-package tests/fixtures/run_package_with_seg_gt_min
```

提示词 + mask 的 HTTP e2e（确定性夹具）：

```powershell
# 终端 1：reference seg service（prompt+mask 夹具来源）
$env:BYES_REF_SEG_FIXTURE_DIR="Gateway/tests/fixtures/run_package_with_seg_prompt_and_mask_gt_min"
python -m uvicorn services.reference_seg_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19231

# 终端 2：inference_service（seg provider=http）
$env:BYES_SERVICE_SEG_PROVIDER="http"
$env:BYES_SERVICE_SEG_ENDPOINT="http://127.0.0.1:19231/seg"
python -m uvicorn services.inference_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19120

# 终端 3：Gateway + 回放/报告
cd Gateway
$env:BYES_ENABLE_SEG="1"
$env:BYES_SEG_BACKEND="http"
$env:BYES_SEG_HTTP_URL="http://127.0.0.1:19120/seg"
$env:BYES_SEG_PROMPT_JSON='{"schemaVersion":"byes.seg_request.v1","targets":["person"],"text":"find person","meta":{"promptVersion":"v1"}}'
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_seg_prompt_and_mask_gt_min --reset
python scripts/report_run.py --run-package tests/fixtures/run_package_with_seg_prompt_and_mask_gt_min
```

期望证据：
- `events/events_v1.jsonl` 同时包含 `seg.prompt` 与 `seg.segment`。
- `seg.segment.payload.segments[*].mask` 保留 `rle_v1`。
- `report.json -> quality.seg` 包含 `maskCoverage`、`maskFramesWithGt`、`maskFramesWithPred`。

## 深度估计（mock/http）

在 Gateway 启用深度事件输出：

```powershell
cd Gateway
$env:BYES_ENABLE_DEPTH="1"
$env:BYES_DEPTH_BACKEND="mock"   # 或 http
$env:BYES_DEPTH_MODEL_ID="mock-depth-v1"
# 使用 http 后端时：
# $env:BYES_DEPTH_HTTP_URL="http://127.0.0.1:19120/depth"
```

期望证据：
- `events/events_v1.jsonl` 包含 `name="depth.estimate"`，并含 `grid`、`backend`、`model`、`endpoint`。
- `report.json -> inference.depth` 从 `depth.estimate` 推断。
- `report.json -> quality.depth` 包含 `absRel`、`rmse`、`delta1`、`coverage`、`latencyMs`。

深度质量评估（网格指标）：

```powershell
python scripts/report_run.py --run-package tests/fixtures/run_package_with_depth_gt_min
python scripts/run_regression_suite.py --suite regression/suites/contract_suite.json --baseline regression/baselines/baseline.json --fail-on-drop
```

`report.json -> quality.depth` 字段：
- `framesTotal / framesWithGt / framesWithPred / coverage`
- `absRel / rmse / delta1`
- `latencyMs`（`p50/p90/max`）
- `topBadCells`（调试样本）

排行榜字段：
- 列：`depth_absrel`、`depth_rmse`、`depth_delta1`、`depth_coverage`、`depth_latency_p90`
- 过滤：`min_depth_delta1`、`max_depth_absrel`、`min_depth_coverage`、`max_depth_latency_p90`
- 排序：`sort=depth_absrel|depth_rmse|depth_delta1|depth_coverage|depth_latency_p90`

参考 depth HTTP 链路（Gateway -> inference_service -> reference_depth_service）：

```powershell
# 终端 1：reference depth service
python -m uvicorn services.reference_depth_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19241

# 终端 2：inference_service（depth provider=http -> reference depth service）
$env:BYES_SERVICE_DEPTH_PROVIDER="http"
$env:BYES_SERVICE_DEPTH_ENDPOINT="http://127.0.0.1:19241/depth"
$env:BYES_SERVICE_DEPTH_MODEL_ID="reference-depth-v1"
python -m uvicorn services.inference_service.app:app --app-dir Gateway --host 127.0.0.1 --port 19120

# 终端 3：Gateway 回放/报告（启用 depth）
cd Gateway
$env:BYES_ENABLE_DEPTH="1"
$env:BYES_DEPTH_BACKEND="http"
$env:BYES_DEPTH_HTTP_URL="http://127.0.0.1:19120/depth"
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_depth_gt_min --reset
python scripts/report_run.py --run-package tests/fixtures/run_package_with_depth_gt_min
```

分割提示词预算扫参（本地工具，不作为 CI 门禁）：

```powershell
python scripts/sweep_seg_prompt_budget.py --run-package tests/fixtures/run_package_with_seg_prompt_budget_min --max-chars 64,128,256 --mode targets_text_boxes_points
```

输出：
- `%TEMP%\byes_seg_prompt_budget\latest.json`
- `%TEMP%\byes_seg_prompt_budget\latest.md`

从已有 `seg.segment` 事件生成受预算控制的 seg 上下文包：

```powershell
curl "http://127.0.0.1:8000/api/seg/context?runId=<run_id>&maxChars=512&maxSegments=16&mode=topk_by_score"
```

响应为 `seg.context.v1`：
- `budget`：实际应用预算（`maxChars/maxSegments/mode`）
- `stats.in/out/truncation`：保留与丢弃的 segment/text 计数
- `text.promptFragment`：可附加到规划器提示词的简洁分割摘要

`report.json` 也会包含 `segContext`（用于排行榜/回归可见性）。

规划上下文包（risk+pov+seg，受预算控制）：

```powershell
# 使用环境/运行时默认预算
curl "http://127.0.0.1:8000/api/plan/context?runId=<run_id>"

# 按请求覆盖（v4.56）
curl "http://127.0.0.1:8000/api/plan/context?runId=<run_id>&ctxMaxChars=512&ctxMode=pov_plus_risk"
```

说明：
- `budgetOverrideUsed=true` 仅出现在 `/api/plan/context` API 响应中，便于使用。
- `plan.context_pack` 事件 payload 保持 `plan.context_pack.v1` 契约兼容（无额外 override 字段）。

## 规划 API（/api/plan）

从 POV 上下文 + 风险事件生成 `ActionPlan v1`。

规划器后端：
- `mock`（默认）：Gateway 内置确定性规划器。
- `http`：调用外部规划器服务（参考 `services/planner_service`）。

默认（`mock`）示例：

```powershell
curl -X POST "http://127.0.0.1:8000/api/plan" `
  -H "Content-Type: application/json" `
  -d '{"runPackage":"Gateway/tests/fixtures/run_package_with_risk_gt_and_pov_min","frameSeq":2,"budget":{"maxChars":2000,"maxTokensApprox":256,"mode":"decisions_plus_highlights"},"constraints":{"allowConfirm":true,"allowHaptic":false,"maxActions":3}}'
```

计划生成时按请求覆盖上下文包（v4.56）：

```powershell
curl -X POST "http://127.0.0.1:8000/api/plan" `
  -H "Content-Type: application/json" `
  -d '{"runPackage":"Gateway/tests/fixtures/run_package_with_risk_gt_and_pov_min","frameSeq":2,"budget":{"maxChars":2000,"maxTokensApprox":256,"mode":"decisions_plus_highlights"},"constraints":{"allowConfirm":true,"allowHaptic":false,"maxActions":3},"contextPackOverride":{"maxChars":512,"mode":"pov_plus_risk"}}'
```

SafetyKernel 护栏：
- `critical`：若缺失 `stop` 则注入，并将非 `stop` 动作强制 `requiresConfirm=true`。
- `high`：对未被门控的动作强制 `requiresConfirm=true`。
- 将动作裁剪到 `constraints.maxActions`，缺失时补默认 `ttlMs=2000`。

审计输出：
- `events/events_v1.jsonl`：追加 `plan.generate` 与 `safety.kernel`（使用 `/api/plan/execute` 时还会追加 `plan.execute`）。
- `report.json`：查看 `plan` 的 `riskLevel`、动作数量/类型、`guardrailsApplied`。
- 排行榜（`/api/run_packages`、`/runs`）：`plan_present`、`plan_risk_level`、`plan_actions`、`plan_guardrails`。

规划上下文包扫参助手（本地工具，不作为 CI 门禁）：

```powershell
python scripts/sweep_plan_context_pack.py `
  --run-package tests/fixtures/run_package_with_risk_gt_and_pov_min `
  --budgets 128,256,512 `
  --modes seg_plus_pov_plus_risk,pov_plus_risk,risk_only
```

输出：
- `%TEMP%\\byes_plan_ctx_sweep\\latest.json`
- `%TEMP%\\byes_plan_ctx_sweep\\latest.md`

最小 execute + confirm 循环：

```powershell
# 1) generate plan
$plan = curl -X POST "http://127.0.0.1:8000/api/plan" `
  -H "Content-Type: application/json" `
  -d '{"runPackage":"Gateway/tests/fixtures/run_package_with_risk_gt_and_pov_min","frameSeq":2,"budget":{"maxChars":2000,"maxTokensApprox":256,"mode":"decisions_plus_highlights"},"constraints":{"allowConfirm":true,"allowHaptic":false,"maxActions":3}}'

# 2) execute plan -> returns uiCommands / pendingConfirms
curl -X POST "http://127.0.0.1:8000/api/plan/execute" `
  -H "Content-Type: application/json" `
  -d "{\"runPackage\":\"Gateway/tests/fixtures/run_package_with_risk_gt_and_pov_min\",\"frameSeq\":2,\"plan\":$plan}"

# 3) submit confirm response
curl -X POST "http://127.0.0.1:8000/api/confirm/response" `
  -H "Content-Type: application/json" `
  -d '{"runId":"fixture-risk-gt","frameSeq":2,"confirmId":"confirm-a1","accepted":true,"runPackage":"Gateway/tests/fixtures/run_package_with_risk_gt_and_pov_min"}'
```

循环写入 `events/events_v1.jsonl` 的事件：
- `plan.execute`
- `ui.command`
- `ui.confirm_request`
- `ui.confirm_response`

HTTP 规划器（reference service）快速演示：

```powershell
# 1) 启动规划器服务
python Gateway/services/planner_service/app.py

# 2) 配置 Gateway 规划器后端
set BYES_PLANNER_BACKEND=http
set BYES_PLANNER_ENDPOINT=http://127.0.0.1:19211/plan

# 3) 运行报告/回放并检查规划器元数据 + 计划质量
python Gateway/scripts/report_run.py --run-package Gateway/tests/fixtures/run_package_with_plan_http_min
```

验证点：
- `events/events_v1.jsonl` 的 `plan.generate` payload 含规划器 `backend/model/endpoint`。
- `report.json` 包含 `plan` 与 `planQuality`。

POV 规划器适配器（`provider=pov`）用于契约/回放：

```powershell
set BYES_PLANNER_BACKEND=http
set BYES_PLANNER_ENDPOINT=http://127.0.0.1:19211/plan
set BYES_PLANNER_PROVIDER=pov
set BYES_PLANNER_ALLOW_RUN_PACKAGE_PATH=1
python Gateway/scripts/report_run.py --run-package Gateway/tests/fixtures/pov_plan_min
```

验证点：
- `report.json.plan.planner.backend == "pov"`
- `report.json.povPlan` 包含 `decisionCoverage`、`actionCoverage`、`consistencyWarnings`
- 契约套件包含 `fixture_pov_plan_min` 以锁定该适配器路径。

实时 POV ingest 演示（不依赖 `runPackagePath`）：

```powershell
# 1) 规划器服务
set BYES_PLANNER_PROVIDER=pov
python Gateway/services/planner_service/app.py

# 2) gateway
python Gateway/main.py

# 3) 导入 POV IR 并生成计划
curl -X POST "http://127.0.0.1:8000/api/pov/ingest" -H "Content-Type: application/json" -d @Gateway/tests/fixtures/pov_ir_v1_min/pov/pov_ir_v1.json
curl -X POST "http://127.0.0.1:8000/api/plan?provider=pov" -H "Content-Type: application/json" -d "{\"runId\":\"fixture-pov-ir-min\",\"frameSeq\":1,\"budget\":{\"maxChars\":2000,\"maxTokensApprox\":256,\"mode\":\"decisions_plus_highlights\"},\"constraints\":{\"allowConfirm\":true,\"allowHaptic\":false,\"maxActions\":3}}"
```

### 规划器 LLM 适配器（可选）

默认不需要 key。LLM 模式为可选开启；当 timeout/HTTP/JSON/schema 校验失败时会回退到 reference 规划器。

```powershell
set BYES_PLANNER_BACKEND=http
set BYES_PLANNER_ENDPOINT=http://127.0.0.1:19211/plan
set BYES_PLANNER_PROVIDER=llm
set BYES_PLANNER_LLM_ENDPOINT=http://127.0.0.1:8088/generate
set BYES_PLANNER_LLM_TIMEOUT_MS=2500
set BYES_PLANNER_PROMPT_VERSION=v1
```

提示词版本说明：
- `v1`：仅 POV 上下文（现有行为）。
- `v2`：可用时包含 `segContext.text.promptFragment`；若无 seg 上下文，行为与 `v1` 完全一致。

可追溯字段：
- `events/events_v1.jsonl`（`plan.generate`）：`plannerProvider`、`promptVersion`、`fallbackUsed`、`fallbackReason`、`jsonValid`
- `events/events_v1.jsonl`（`plan.request`）：`schemaVersion=byes.plan_request.v1`、上下文纳入/字符/截断统计
- `events/events_v1.jsonl`（`plan.rule_applied`）：确定性 seg-hint 规则命中，含 `hazardHint` + `matchedKeywords`
- `report.json`（`plan.planner.*`、`planQuality.*`）：回退与 JSON 有效性状态
- `report.json`（`planRequest`、`planEval.ruleAppliedCount`）：请求预算与规则命中聚合指标
- `/api/run_packages`：`plan_fallback_used`、`plan_json_valid`、`plan_prompt_version`

规划器 HTTP 请求契约（v4.53）：
- `Gateway/contracts/byes.plan_request.v1.json`
- 包含 `risk + contexts.pov + contexts.seg + meta.promptVersion`

## 规划器评估与消融

`report.json` 现包含 `planEval`：
- 交互成本：`confirm.requests/responses/timeouts/pending`
- 安全动作：`actions.stopCount`、`actions.blockingCount`
- 护栏依赖：`guardrails.appliedCount`、`guardrails.overrideRate`
- 过度保守行为：`overcautious.rate`（`riskLevel!=critical` 但发生 `stop/confirm`）
- 延迟：`latencyMs`（plan.generate）与 `executeLatencyMs`（plan.execute）

一条命令扫参（提供方/提示词/预算）：

```powershell
python Gateway/scripts/ablate_planner.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_and_pov_min --providers reference,llm --prompt-versions v1 --pov-budgets 128,256
```

输出：
- `%TEMP%\\byes_plan_ablation\\latest.json`
- `%TEMP%\\byes_plan_ablation\\latest.md`

推荐规则：
- 在满足 `critical_fn==0` 前提下最小化 `confirm_timeouts`
- 然后最小化 `plan_latency_p90`
- 再最大化 `qualityScore`

## 消融：POV Budget Sweep

一条命令比较上下文预算：

```powershell
python scripts/run_ablation_pov_budget.py --run-package tests/fixtures/run_package_with_risk_gt_and_pov_min --budgets 256,512,1024 --mode decisions_plus_highlights --use-http 0
```

输出：
- `%TEMP%\byes_pov_ablation\latest.json`
- `%TEMP%\byes_pov_ablation\latest.md`

如何理解推荐结果：
- 默认规则是满足 `critical_fn==0` 时最小化 `riskLatencyP90`，然后最大化 `qualityScore`。
- 使用 `latest.md` 表格检查上下文压缩（`ctxTok`、`ctxChars`）与质量/延迟指标之间关系。

## 排行与报告

- API 列表：`GET /api/run_packages`
- HTML 列表：`GET /runs`
- 运行详情：`GET /runs/{run_id}`
- 比较两个运行：`GET /runs/compare?ids=<runA>,<runB>`
- 导出：
  - `GET /api/run_packages/export.json`
  - `GET /api/run_packages/export.csv`

重要排行榜字段：
- `quality_score`
- `confirm_timeouts`
- `missCriticalCount` / `critical_misses`
- `risk_latency_p90`、`risk_latency_max`
- `plan_present`、`plan_risk_level`、`plan_actions`、`plan_guardrails`、`plan_score`
- `plan_fallback_used`、`plan_json_valid`、`plan_prompt_version`

## Frame User E2E（Capture -> Feedback）

v4.59 增加采集/ACK 延迟追踪，使“用户感知 E2E”可见：
- `frame.input` 事件（`frame.input.v1`）：设备采集时间戳 + gateway 接收时间戳。
- `frame.ack` 事件（`frame.ack.v1`）：设备反馈 ACK（`tts|overlay|haptic|any`），其中 `overlay` 在报告中视为 AR 反馈。
- `frame.user_e2e` 事件（`frame.e2e.v1` payload）：`totalMs = feedbackTsMs - t0`。

v4.60 增加反馈类别桶与 Unity 接线：
- `report.json.frameUserE2E.byKind.{tts,ar,haptic,other}`，含 `p50/p90/p99/max`。
- `report.json.frameUserE2E.tts`（等价 TTFA 桶摘要）。
- `/api/run_packages` 列：`frame_user_e2e_tts_p90`、`frame_user_e2e_tts_max`、`frame_user_e2e_ar_p90`、`frame_user_e2e_ar_max`、`ack_kind_diversity`。
- Unity 运行时引导（无需改场景）：`Assets/Scripts/BYES/Telemetry/ByesFrameTelemetry.cs`。

最小 API 流程：

```powershell
# 1) upload/process frame (capture timestamp can be in meta or form field captureTsMs)
curl -X POST "http://127.0.0.1:8000/api/frame" `
  -F "image=@Gateway/tests/fixtures/run_package_with_frame_user_e2e_min/frames/frame_1.png" `
  -F "meta={\"runId\":\"demo-user-e2e\",\"frameSeq\":1,\"captureTsMs\":1713002000000,\"runPackage\":\"Gateway/tests/fixtures/run_package_with_frame_user_e2e_min\"}"

# 2) ACK when user feedback is rendered/played
curl -X POST "http://127.0.0.1:8000/api/frame/ack" `
  -H "Content-Type: application/json" `
  -d "{\"runId\":\"demo-user-e2e\",\"frameSeq\":1,\"feedbackTsMs\":1713002000120,\"kind\":\"tts\",\"accepted\":true,\"runPackage\":\"Gateway/tests/fixtures/run_package_with_frame_user_e2e_min\"}"
```

报告与排行榜字段：
- `report.json.frameUserE2E.totalMs.{p50,p90,max}`
- `report.json.frameUserE2E.byKind.<kind>.totalMs.{p50,p90,max}`
- `report.json.frameUserE2E.tts.{p50,p90,max}`
- `report.json.frameUserE2E.coverage.ratio`（ACK 覆盖率）
- `/api/run_packages`：`frame_user_e2e_p90`、`frame_user_e2e_max`、`frame_user_e2e_tts_p90`、`frame_user_e2e_ar_p90`、`ack_kind_diversity`、`ack_coverage`

## 脚本索引（常用）

- `scripts/replay_run_package.py`：回放回放包并产出事件/指标。
- `scripts/report_run.py`：从单个回放包生成报告。
- `scripts/report_packages.py`：批量生成报告。
- `scripts/lint_run_package.py`：校验回放包结构与事件 schema。
- `scripts/run_regression_suite.py`：基线对比与门禁检查。
- `scripts/bench_risk_latency.py`：汇总事件中的风险延迟。
- `scripts/sweep_depth_input_size.py`：比较 ONNX 深度输入尺寸。
- `scripts/calibrate_risk_thresholds.py`：带 FN 报告的阈值网格搜索。

## 参考资料

- 根项目入口：`README.md`
- 推理提供方与部署：`Gateway/services/inference_service/README.md`
- 事件 schema 细节：`docs/event_schema_v1.md`
- 架构总览：`docs/ARCHITECTURE.md`
- 5 分钟演示脚本：`docs/QUICK_DEMO.md`
- 术语：`docs/GLOSSARY.md`
- 命令索引：`docs/COMMANDS.md`

## 模型/制品清单（`/api/models`）

用于回答“这台机器当前需要哪些模型/环境变量/端点”。

- API：
  - `GET /api/models`
  - 返回 `byes.models.v1`，包含按组件划分的 provider/model/endpoint 以及 required/optional 依赖项。
- CLI 自检：
  - `python Gateway/scripts/verify_models.py --json`
  - `python Gateway/scripts/verify_models.py --check --quiet`

解读：
- `missingRequiredTotal == 0`：所有已启用组件配置完整。
- `missingRequiredTotal > 0`：一个或多个已启用组件缺少必需 env/file/endpoint 配置。
- `provider=mock`：组件已启用，但不需要真实模型制品。
