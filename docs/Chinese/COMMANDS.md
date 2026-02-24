# 命令索引（PowerShell）

## 测试与校验

1. 运行 Gateway 测试：

```powershell
cd Gateway
python -m pytest -q
```

2. 校验回放包夹具：

```powershell
python scripts/lint_run_package.py --run-package tests/fixtures/run_package_with_events_v1_min
```

3. 运行带门禁的回归套件：

```powershell
cd ..
python Gateway/scripts/run_regression_suite.py --suite Gateway/regression/suites/baseline_suite.json --baseline Gateway/regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
```

## 回放与报告

4. 回放一个夹具：

```powershell
python Gateway/scripts/replay_run_package.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min --reset
```

5. 生成单次报告：

```powershell
python Gateway/scripts/report_run.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min
```

6. 批量生成报告：

```powershell
python Gateway/scripts/report_packages.py --root Gateway/tests/fixtures --out "$env:TEMP\byes_reports"
```

## 运行时 / 仪表盘

7. 启动 Gateway：

```powershell
cd Gateway
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

8. 启动 inference_service：

```powershell
python -m uvicorn services.inference_service.app:app --host 127.0.0.1 --port 19120
```

## 优化与标定（可选）

9. 扫描 ONNX 深度输入尺寸：

```powershell
python Gateway/scripts/sweep_depth_input_size.py --run-package Gateway/tests/fixtures/run_package_with_risk_gt_min --sizes 518,384,256 --out "$env:TEMP\depth_sweep.json" --port 19120 --risk-url http://127.0.0.1:19120/risk
```

10. 标定风险阈值：

```powershell
python Gateway/scripts/calibrate_risk_thresholds.py --run-package Gateway/tests/fixtures/run_package_risk_calib_10f --risk-url http://127.0.0.1:19120/risk --sizes 256 --out "$env:TEMP\risk_calib_out.json"
```

## v4.82 深度时序一致性（DA3 fixture 路径）

11. 对时序深度夹具生成报告：

```powershell
python Gateway/scripts/report_run.py --run-package Gateway/tests/fixtures/run_package_with_depth_temporal_min
```

重点检查：
- `quality.depthTemporal.jitterAbs.p90`
- `quality.depthTemporal.flickerRateNear.mean`
- `quality.depthTemporal.scaleDriftProxy.p90`
- `quality.depthTemporal.refViewStrategyDiversityCount`

12. 运行契约套件中的 depth temporal 门禁：

```powershell
python Gateway/scripts/run_regression_suite.py --suite Gateway/regression/suites/contract_suite.json --baseline Gateway/regression/baselines/baseline.json --fail-on-drop
```

查看 run `fixture_with_depth_temporal_contract`：
- `depthEventsPresent=True`
- `depthPayloadSchemaOk=True`
- `depthTemporalPresent=True`

13. 用 DA3 temporal profile 跑 matrix（`replay=0`）：

```powershell
cd Gateway
python scripts/run_dataset_benchmark.py --root artifacts/imports/v468_ego4d_demo --out artifacts/benchmarks/v482_demo --matrix 1 --profiles scripts/profiles/v482_depth_temporal_profiles.json --replay 0 --shuffle 0 --max 10
```

## 契约 / 模型清单 / SLAM（跨版本常用）

14. 校验 contracts lock：

```powershell
python Gateway/scripts/verify_contracts.py --check-lock
```

15. 校验模型与工件依赖：

```powershell
python Gateway/scripts/verify_models.py --check --quiet
```

16. 将 pySLAM TUM 轨迹注入 `slam.pose` 事件：

```powershell
python Gateway/scripts/ingest_pyslam_tum.py --run-package <run_package_dir> --tum <trajectory.tum> --align-mode auto --replace-existing 1
```

17. 基于 GT TUM 评测 SLAM 轨迹误差（ATE/RPE）：

```powershell
python Gateway/scripts/eval_slam_tum.py --run-package <run_package_dir>
```
