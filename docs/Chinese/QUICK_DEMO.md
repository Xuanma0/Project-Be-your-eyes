# 5 分钟演示（教授 / 评审）

本演示仅使用内置夹具，不需要下载模型。

## 0) 前置条件

```powershell
cd Gateway
python -m pytest -q
```

预期：测试通过。

## 1) 回放一个夹具

```powershell
python scripts/replay_run_package.py --run-package tests/fixtures/run_package_with_risk_gt_min --reset
```

该步骤会：
- 回放帧和元数据；
- 生成 `events/events_v1.jsonl`；
- 将回放产物写入夹具回放输出目录。

## 2) 生成报告

```powershell
python scripts/report_run.py --run-package tests/fixtures/run_package_with_risk_gt_min
```

检查：
- `report.json`
- `report.md`

重点字段：
- `inference.risk`
- `quality.depthRisk.critical.missCriticalCount`
- `quality.riskLatencyMs`
- `quality.qualityScore`

## 3) 运行回归门禁

```powershell
cd ..
python Gateway/scripts/run_regression_suite.py --suite Gateway/regression/suites/baseline_suite.json --baseline Gateway/regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
```

预期：
- 每个夹具都会打印 score 和 `critical_fn`；
- 无回归时退出码为 `0`。

## 4) 打开排行榜

启动 Gateway 应用：

```powershell
cd Gateway
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

然后打开：
- `http://127.0.0.1:8000/runs`
- `http://127.0.0.1:8000/api/run_packages`

重点关注：
- `Quality`
- `ConfirmTimeouts`
- `Critical FN`
- `Risk p90(ms)`

## 可选：接入真实 ONNX 深度

若要演示真实深度推理：

1. 安装可选依赖：

```powershell
python -m pip install -r Gateway/services/inference_service/requirements-onnx-depth.txt
```

2. 在仓库外准备模型（示例）：
- `D:\models\depth_anything_v2_small\model.onnx`

3. 校验模型：

```powershell
python Gateway/services/inference_service/tools/verify_depth_onnx.py --path D:\models\depth_anything_v2_small\model.onnx --expected-sha256 <sha256>
```

4. 以 ONNX 深度运行 `inference_service`，并重复回放/报告流程。
