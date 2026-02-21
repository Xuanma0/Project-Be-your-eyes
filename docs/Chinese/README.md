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

### 1) 仅运行 Gateway 测试

```powershell
cd Gateway
python -m pytest -q
```

### 2) 最小回放

```powershell
cd ..
python Gateway/scripts/replay_run_package.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min --reset
```

### 3) 生成报告

```powershell
python Gateway/scripts/report_run.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min
```

### 4) 运行回归

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

## 里程碑（v4.9 -> v4.29）

| Version | 主题 | 新增内容 |
|---|---|---|
| v4.9 | 可回放输入 | RunPackage 回放流程与基于夹具的可复现能力 |
| v4.13-v4.15 | 事件标准 + CI | `events_v1` schema、记录器兼容、CI 中回归套件 |
| v4.16-v4.21 | 可插拔推理 | OCR/risk 后端注册（mock/http）、深度感知风险演进 |
| v4.23-v4.26 | ONNX 深度 + 可观测性 | ONNX 深度提供方、输入尺寸扫参、延迟分解、排行榜延迟列 |
| v4.27-v4.29 | 标定 + 安全门禁 | 阈值标定闭环、`critical FN` 可解释性、默认值固化、回归/CI 的 `critical FN == 0` 门禁 |

## 下一步阅读

- Gateway 开发与评估指南：`Gateway/README.md`
- 推理 provider/部署指南：`Gateway/services/inference_service/README.md`
- 系统架构：`docs/ARCHITECTURE.md`
- 5 分钟演示脚本：`docs/QUICK_DEMO.md`
- 术语：`docs/GLOSSARY.md`
- 命令索引：`docs/COMMANDS.md`
