# Project-Be-your-eyes（中文说明）

Project-Be-your-eyes（Be Your Eyes）是一个面向 Unity + Gateway + 可插拔推理后端的事件驱动辅助感知系统，支持可回放评估与安全门禁，覆盖 `risk + ocr` 流水线。

## 为什么要做这个项目

- 可回放 `RunPackage`：基于已记录的帧/事件/指标进行确定性离线评估。
- 统一事件 schema：以 `events/events_v1.jsonl` 记录工具结果与延迟证据。
- 报告与质量指标：输出 `report.json` 与 markdown 报告，覆盖 OCR/risk/safety 分解。
- 运行排行榜：按质量、延迟、确认超时、关键漏检进行筛选与排序。
- CI 回归门禁：质量下降检查 + 安全硬门禁（`critical FN == 0`）。
- 可插拔推理：支持 mock/http 后端；可选接入真实 OCR 与 ONNX 深度提供方。

## 快速开始（PowerShell）

### 1) 准备 Python 环境（Gateway 必需）

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

### 2) 仅运行 Gateway 测试

```powershell
cd Gateway
python -m pytest -q
```

### 3) 最小回放

```powershell
cd ..
python Gateway/scripts/replay_run_package.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min --reset
```

### 4) 生成报告

```powershell
python Gateway/scripts/report_run.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min
```

### 5) 运行回归

```powershell
python Gateway/scripts/run_regression_suite.py --suite Gateway/regression/suites/baseline_suite.json --baseline Gateway/regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
```

## POV-compiler -> BYE 契约

- 单一 schema 来源：`schemas/pov_ir_v1.schema.json`
- 将 POV IR 导入 BYES events v1：

```powershell
python Gateway/scripts/ingest_pov_ir.py --run-package <run_package_dir> --pov-ir <pov_ir.json> --strict 1
```

- 运行契约回归套件：

```powershell
python Gateway/scripts/run_regression_suite.py --suite Gateway/regression/suites/contract_suite.json --baseline Gateway/regression/baselines/baseline.json --fail-on-drop
```

## 可选：真实 ONNX 深度（Depth Anything V2 Small）

### 安装可选依赖

```powershell
python -m pip install -r Gateway/services/inference_service/requirements-onnx-depth.txt
```

### 下载模型（不要存入仓库）

- 模型：`onnx-community/depth-anything-v2-small -> onnx/model.onnx`
- 本地路径示例：`D:\models\depth_anything_v2_small\model.onnx`

### 校验 sha256

```powershell
python Gateway/services/inference_service/tools/verify_depth_onnx.py --path D:\models\depth_anything_v2_small\model.onnx --expected-sha256 <sha256_from_hf_page>
```

### 启动 inference_service（HTTP + ONNX depth）

```powershell
cd Gateway
$env:BYES_SERVICE_RISK_PROVIDER="heuristic"
$env:BYES_SERVICE_DEPTH_PROVIDER="onnx"
$env:BYES_SERVICE_DEPTH_ONNX_PATH="D:\models\depth_anything_v2_small\model.onnx"
$env:BYES_SERVICE_DEPTH_MODEL_ID="depth-anything-v2-small-onnx"
$env:BYES_SERVICE_DEPTH_INPUT_SIZE="256"
$env:BYES_SERVICE_RISK_DEBUG="1"
python -m uvicorn services.inference_service.app:app --host 127.0.0.1 --port 19120
```

### 扫描输入尺寸（518/384/256）

```powershell
python Gateway/scripts/sweep_depth_input_size.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min --sizes 518,384,256 --out "$env:TEMP\byes_depth_sweep.json" --port 19120 --risk-url http://127.0.0.1:19120/risk
```

当前默认 ONNX 深度输入尺寸已标定并固定为 `256`（仍可通过环境变量覆盖）。

## 我们如何评估安全与有效性

`qualityScore` 基于惩罚机制，强调安全优先：

- 关键漏检（`critical FN`）被视为硬安全风险。
- 确认超时 / 缺失响应会被惩罚。
- 深度风险 FP/FN 与检测延迟通过风险质量项惩罚。
- 有 OCR 真值时，OCR 不匹配指标（CER/WER/完全匹配）会计入评分。
- 统计风险延迟（`p50/p90/p99/max`）以体现性能可见性。

`report.json` 示例片段：

```json
{
  "inference": {
    "risk": {"backend": "http", "model": "heuristic-risk-v2+depth=depth-anything-v2-small-onnx", "endpoint": "http://127.0.0.1:19120/risk"}
  },
  "quality": {
    "depthRisk": {
      "critical": {"missCriticalCount": 0},
      "detectionDelayFrames": {"p90": 0, "max": 0}
    },
    "riskLatencyMs": {"count": 10, "p50": 88, "p90": 131, "max": 168},
    "qualityScore": 89.0,
    "qualityScoreBreakdown": {"risk": 42.0, "ocr": 25.0, "safetyBehavior": 22.0}
  }
}
```

## 关键目录

```text
Gateway/                              # 核心 gateway 运行时 + API + 测试
Gateway/services/inference_service/   # 可插拔 OCR/risk/depth 推理服务
Gateway/scripts/                      # 回放/报告/回归/扫参/标定工具
Gateway/regression/                   # 套件定义、基线、输出
docs/                                 # 架构/演示/术语/命令文档
Assets/                               # Unity 客户端与场景集成
```

## 里程碑（v4.9 -> v4.82）

| Version | 主题 | 新增内容 |
|---|---|---|
| v4.9 | 可回放输入 | RunPackage 回放流程与基于夹具的可复现能力 |
| v4.13-v4.15 | 事件标准 + CI | `events_v1` schema、记录器兼容、CI 中回归套件 |
| v4.16-v4.21 | 可插拔推理 | OCR/risk 后端注册（mock/http）、深度感知风险演进 |
| v4.23-v4.26 | ONNX 深度 + 可观测性 | ONNX 深度提供方、输入尺寸扫参、延迟分解、排行榜延迟列 |
| v4.27-v4.29 | 标定 + 安全门禁 | 阈值标定闭环、`critical FN` 可解释性、默认值固化、回归/CI 的 `critical FN == 0` 门禁 |
| v4.30-v4.41 | 规划器与契约冻结 | planEval、POV 规划适配、在线 POV ingest、`/api/contracts` 与 lock gate |
| v4.42-v4.50 | Seg 能力闭环 | seg provider、seg/mask 质量、SAM3 fixture 链路、prompt 合同与透传 |
| v4.51-v4.60 | 上下文与端到端时延 | seg/plan context pack、frame e2e & user-e2e（input/ack） |
| v4.61-v4.70 | Depth/OCR/SLAM 与 benchmark | depth/ocr/slam providers、model manifest、dataset benchmark + matrix |
| v4.71-v4.79 | pySLAM + costmap/fused | 轨迹注入与对齐、ATE/RPE、costmap/fused/shift gate、online/final 对比 |
| v4.80-v4.82 | 跟踪与时序一致性 | seg trackId 动态缓存、DA3 ref-view 透传、depthTemporal 指标闭环 |

完整版本清单请见：`docs/Chinese/RELEASE_NOTES.md`（英文：`docs/English/RELEASE_NOTES.md`）。

## v4.82 文档同步（深度时序一致性）

本轮文档已同步中英文，覆盖以下新增能力：
- DA3 `refViewStrategy` 透传（Gateway -> inference_service -> da3_depth_service）
- 报告新增 `quality.depthTemporal`：
  - `jitterAbs`
  - `flickerRateNear`
  - `scaleDriftProxy`
  - `refViewStrategyDiversityCount`
- 排行榜与 benchmark matrix 新增深度时序列，可直接做 profile 对比。

推荐先读：
- `docs/Chinese/ARCHITECTURE.md`
- `docs/Chinese/COMMANDS.md`
- `docs/Chinese/event_schema_v1.md`
- `docs/Chinese/QUICK_DEMO.md`
- `docs/Chinese/RELEASE_NOTES.md`

## 下一步阅读

- Gateway 开发与评估指南：`Gateway/README.md`
- 推理提供方/部署指南：`Gateway/services/inference_service/README.md`
- 系统架构：`docs/Chinese/ARCHITECTURE.md`（英文版见 `docs/English/ARCHITECTURE.md`）
- 5 分钟演示脚本：`docs/Chinese/QUICK_DEMO.md`
- 术语：`docs/Chinese/GLOSSARY.md`
- 命令索引：`docs/Chinese/COMMANDS.md`

## 文档目录

### 根目录

- [README.md](../../README.md)

### docs/English

- [docs/English/README.md](../English/README.md)
- [docs/English/ARCHITECTURE.md](../English/ARCHITECTURE.md)
- [docs/English/COMMANDS.md](../English/COMMANDS.md)
- [docs/English/contracts.md](../English/contracts.md)
- [docs/English/event_schema_v1.md](../English/event_schema_v1.md)
- [docs/English/GLOSSARY.md](../English/GLOSSARY.md)
- [docs/English/hazard_taxonomy_v1.md](../English/hazard_taxonomy_v1.md)
- [docs/English/pov_planner_adapter.md](../English/pov_planner_adapter.md)
- [docs/English/QUICK_DEMO.md](../English/QUICK_DEMO.md)
- [docs/English/RELEASE_NOTES.md](../English/RELEASE_NOTES.md)

### docs/Chinese

- [docs/Chinese/README.md](README.md)
- [docs/Chinese/ARCHITECTURE.md](ARCHITECTURE.md)
- [docs/Chinese/COMMANDS.md](COMMANDS.md)

## v4.86 补充（Unity 端闭环）

- ActionPlan 执行支持 Quest 控制器触觉反馈（设备 `supportsImpulse` 时生效）。
- Confirm 输入映射：
  - Editor：`Y` 接受，`N` 拒绝
  - XR：`primaryButton` 接受，`secondaryButton` 拒绝
- Gateway 报表与排行榜新增 `hapticAckRate` / `haptic_ack_rate`，用于观察 Unity 端是否真实执行触觉回执。
- [docs/Chinese/contracts.md](contracts.md)
- [docs/Chinese/event_schema_v1.md](event_schema_v1.md)
- [docs/Chinese/GLOSSARY.md](GLOSSARY.md)
- [docs/Chinese/hazard_taxonomy_v1.md](hazard_taxonomy_v1.md)
- [docs/Chinese/pov_planner_adapter.md](pov_planner_adapter.md)
- [docs/Chinese/QUICK_DEMO.md](QUICK_DEMO.md)
- [docs/Chinese/RELEASE_NOTES.md](RELEASE_NOTES.md)

### Gateway 核心文档

- [Gateway/README.md](../../Gateway/README.md)
- [Gateway/docs/Chinese/README.md](../../Gateway/docs/Chinese/README.md)
- [Gateway/regression/README.md](../../Gateway/regression/README.md)

### Gateway 服务文档

- [Gateway/services/inference_service/README.md](../../Gateway/services/inference_service/README.md)
- [Gateway/services/planner_service/README.md](../../Gateway/services/planner_service/README.md)
- [Gateway/services/reference_depth_service/README.md](../../Gateway/services/reference_depth_service/README.md)
- [Gateway/services/reference_seg_service/README.md](../../Gateway/services/reference_seg_service/README.md)

### Gateway 服务提示词文档

- [Gateway/services/planner_service/prompts/planner_system.md](../../Gateway/services/planner_service/prompts/planner_system.md)
- [Gateway/services/planner_service/prompts/planner_user.md](../../Gateway/services/planner_service/prompts/planner_user.md)

### Gateway 外部服务文档

- [Gateway/external/real_depth_service/README.md](../../Gateway/external/real_depth_service/README.md)
- [Gateway/external/real_ocr_service/README.md](../../Gateway/external/real_ocr_service/README.md)
- [Gateway/external/real_vlm_service/README.md](../../Gateway/external/real_vlm_service/README.md)

### Gateway 测试夹具文档

- [Gateway/tests/fixtures/pov_ir_v1_min/README.md](../../Gateway/tests/fixtures/pov_ir_v1_min/README.md)
- [Gateway/tests/fixtures/pov_plan_min/README.md](../../Gateway/tests/fixtures/pov_plan_min/README.md)
- [Gateway/tests/fixtures/run_package_with_plan_http_min/README.md](../../Gateway/tests/fixtures/run_package_with_plan_http_min/README.md)
- [Gateway/tests/fixtures/run_package_with_plan_llm_stub_min/README.md](../../Gateway/tests/fixtures/run_package_with_plan_llm_stub_min/README.md)
- [Gateway/tests/fixtures/run_package_with_risk_gt_and_pov_min/README.md](../../Gateway/tests/fixtures/run_package_with_risk_gt_and_pov_min/README.md)
- [Gateway/tests/fixtures/run_package_with_events_v1_min/report.md](../../Gateway/tests/fixtures/run_package_with_events_v1_min/report.md)
- [Gateway/tests/fixtures/run_package_with_schema_v1_events_min/report.md](../../Gateway/tests/fixtures/run_package_with_schema_v1_events_min/report.md)

### Unity / Assets 文档

- [Assets/BeYourEyes/Docs/architecture.md](../../Assets/BeYourEyes/Docs/architecture.md)
- [Assets/BeYourEyes/Docs/Spatial Audio Demo.md](../../Assets/BeYourEyes/Docs/Spatial%20Audio%20Demo.md)
- [Assets/Samples/XR Hands/1.7.1/HandVisualizer/README.md](../../Assets/Samples/XR%20Hands/1.7.1/HandVisualizer/README.md)
