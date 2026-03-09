# REPO_FACT_AUDIT_FOR_PAPER

## 0. 一页结论
- 这个仓库不是单一 demo；它是一个混合单仓，包含 Unity/Quest 前端、Python Gateway、独立推理/规划/SLAM 参考服务，以及较完整的 run-package 评测与回放工具链。
- 从代码证据看，当前最真实的系统形态是“可运行原型 + 强工程化评测/回放框架”，而不是已经收敛完成的产品系统，也不是以新算法为中心的论文代码。
- 当前最稳妥的主系统入口是 Unity 的 `Assets/Scenes/Quest3SmokeScene.unity` 与 Python 的 `Gateway/main.py`；前者是唯一启用的构建场景，后者是实际聚合 `/api/frame`、`/ws/events`、`/api/assist`、`/api/plan`、录制与资产接口的后端总入口。
- Quest 端的主链路已经打通到“采集图像 -> 上传 Gateway -> 后端推理/事件生成 -> WebSocket/asset 回传 -> HUD/TTS/haptic/ack”，这一点有较强代码证据支撑。
- 后端已经实现多 provider 抽象、模式切换、缓存、录制、报告、回放、回归测试、合同测试；这部分是当前仓库最强、最像系统论文贡献的区域。
- 与“论文里想写的理想系统”相比，当前代码最明显的现实特征是“过渡态”: Unity 侧同时保留旧的 `BeYourEyes.*` 事件总线路径与新的 `BYES.*` Quest smoke 路径；后端同时保留旧的 scheduler/tool-registry/fusion 线路与新的 inference-v1 事件线路。
- OCR、检测、风险感知、深度、分割、SLAM pose、录制、报告等能力都能在 repo 中找到明确实现或接口；但并不是每个能力都已经进入当前 Quest smoke 主链默认配置。
- “开放词汇检测”只能保守写成 prompt-conditioned detection path；代码里确有 `prompt`/`targets` 传递与 `UltralyticsDetProvider.set_classes` 尝试，但不能直接上升为成熟 open-vocabulary 方法贡献。
- “主动感知”“手眼协调”“VLM/VLA 控制”“完整 3D 建图/SLAM 用户闭环”都不能强写成已经在当前主系统中稳定落地的能力；其中一些只有后端上下文/适配器/服务代理，另一些只存在于手势 UI 或离线评测侧。
- 规划与大模型相关能力不是完全没有代码；`/api/plan`、`planner_service`、`RealVlmTool`、`PlanClient`/`ActionPlanExecutor` 都存在。但当前 Quest smoke 场景没有把 `PlanClient`/`PlanExecutor`/`ActionPlanExecutor` 明确放进主场景主链，因而不能把 LLM/VLM 规划写成“当前默认用户路径”。
- 低延迟相关设计有真实实现，包括 fast/slow 两级队列、TTL、取消旧帧、preempt window、事件 TTL/reorder guard、本地 fallback、asset cache、frame cache、assist 重提交流程；但“低延迟效果”本身仍需结果支撑，代码只能证明 low-latency-oriented design，不证明性能结论。
- 这个仓库最适合支撑的论文定位是“assistive AI system / prototype / engineering-heavy systems paper”，而不是纯算法论文。
- 当前最有把握的论文贡献点应集中在：Quest 端到端辅助视觉原型、模式感知的异步调度与安全降级、run-package 可观测性与评测框架、多 provider 真值状态与外部服务封装。
- 当前绝不能过度宣称的点包括：SOTA 性能、用户收益、已验证实时性、完整端边云协同优势、成熟主动感知、成熟手眼协调、已完成用户研究、已完成系统性鲁棒性验证。

## 1. 仓库基本信息
- 仓库类型: 混合单仓/monorepo。Unity 工程、Python Gateway、独立服务、测试、回归、工件目录共存。
- 主要语言/框架: C# + Unity 6000.3.10f1；Python + FastAPI/Flask；少量 PowerShell/CI 脚本。
- 核心依赖:
  - Unity: `Packages/manifest.json:3`, `Packages/manifest.json:4`, `Packages/manifest.json:17`, `Packages/manifest.json:18`, `Packages/manifest.json:20` 显示 `NativeWebSocket`、`com.unity.ai.inference`、`XR Hands`、`XR Interaction Toolkit`、`Meta OpenXR`。
  - Python: `Gateway/requirements.txt:1`, `Gateway/requirements.txt:2`, `Gateway/requirements.txt:8` 显示 `fastapi`、`uvicorn`、`pytest` 等。
- 主要运行环境:
  - Unity 构建主场景: `ProjectSettings/EditorBuildSettings.asset:9` 只有 `Assets/Scenes/Quest3SmokeScene.unity` 启用。
  - Unity 版本: `ProjectSettings/ProjectVersion.txt:1`。
  - Gateway CI: `.github/workflows/gateway-ci.yml:36`, `.github/workflows/gateway-ci.yml:40`, `.github/workflows/gateway-ci.yml:44`, `.github/workflows/gateway-ci.yml:52`。
- git 状态:
  - 当前分支: `feature/unity-skeleton`
  - HEAD: `6472fff`
  - 最近提交: `6472fff 2026-03-08 fix(v5.08.2): real bring-up & ux hotfix (provider truth fail-closed + overlay asset cache + passthrough fallback + menu/controller polish)`
  - 脏工作区: `.gitignore`, `Gateway/main.py`, `tools/quest3/quest3_usb_realstack_v5_08_2.cmd` 有未提交修改。
- 目录总览:
  - 根目录: `.github`, `Assets`, `Gateway`, `Packages`, `ProjectSettings`, `docs`, `schemas`, `tools` 等。
  - `Assets/`: `BeYourEyes`, `Scenes`, `Scripts`, `Prefabs`, `XR` 等。
  - `Gateway/`: `main.py`, `byes/`, `services/`, `scripts/`, `tests/`, `regression/`, `artifacts/`。
  - `Gateway/services/`: `inference_service`, `planner_service`, `pyslam_service`, `reference_*`, `sam3_seg_service`, `da3_depth_service`。
- 仓库成熟度判断: “可运行原型（prototype）+ 较强回放/评测/回归基础设施”。不是“仅有框架”，也还不是“产品化雏形已收敛”。

## 2. 主系统入口与主链路
- 主入口列表:
  - Unity 构建场景: `Assets/Scenes/Quest3SmokeScene.unity`
  - Unity 运行引导: `Assets/BeYourEyes/AppBootstrap.cs:11`, `Assets/BeYourEyes/AppBootstrap.cs:51`
  - Unity Quest smoke 面板: `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`
  - Unity 采集/上传控制器: `Assets/BeYourEyes/Unity/Interaction/ScanController.cs:15`
  - Unity HTTP/WS 客户端: `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:24`
  - 后端总入口: `Gateway/main.py:2695`
  - 独立推理服务入口: `Gateway/services/inference_service/app.py:47`
  - 独立规划服务入口: `Gateway/services/planner_service/app.py:592`
  - 独立 pySLAM 服务入口: `Gateway/services/pyslam_service/app.py:39`
- 我判断的主入口:
  - 前端主入口: `Quest3SmokeScene`。证据是它是唯一启用构建场景，且包含 `ByesQuest3ConnectionPanelMinimal`、`GatewayClient`、`ScanController`、`GatewayWsClient`、`AppBootstrap`。
  - 后端主入口: `Gateway/main.py`。它统一暴露帧上传、能力查询、assist、record、plan、confirm、ws 事件、assets 等接口。
- 主调用链（按时序）:
  1. Quest 场景启动，加载 `AppBootstrap` 与 smoke 组件。证据: `Assets/Scenes/Quest3SmokeScene.unity:2223`, `Assets/Scenes/Quest3SmokeScene.unity:2508`, `Assets/Scenes/Quest3SmokeScene.unity:2602`。
  2. 用户通过面板/手势菜单/控制器触发扫描、模式切换、查找、录制等。证据: `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs:369`, `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs:373`, `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs:1463`, `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs:1551`。
  3. `ScanController` 从 `IByesFrameSource` 抓取 JPG 帧，打包 meta。证据: `Assets/BeYourEyes/Unity/Interaction/ScanController.cs:402`, `Assets/BeYourEyes/Unity/Interaction/ScanController.cs:403`, `Assets/BeYourEyes/Unity/Interaction/ScanController.cs:835`。
  4. 帧通过 `/api/frame` 上传到 Gateway。证据: `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:657`, `Assets/BeYourEyes/Adapters/Networking/GatewayFrameUploader.cs:56`, `Gateway/main.py:2907`。
  5. Gateway 记录帧、缓存帧、把帧交给 scheduler，并立即执行 inference-v1 路径。证据: `Gateway/main.py:2175`, `Gateway/main.py:2185`, `Gateway/main.py:3039`, `Gateway/main.py:777`, `Gateway/main.py:789`。
  6. 后端根据 mode/target 运行 OCR、risk、det、depth、seg、slam，并发出 `byes.event.v1` 事件与 overlay asset。证据: `Gateway/main.py:1553`, `Gateway/main.py:1710`, `Gateway/main.py:1772`, `Gateway/main.py:1900`, `Gateway/main.py:1963`, `Gateway/main.py:2043`, `Gateway/main.py:2088`。
  7. Unity 通过 `/ws/events` 收事件，并按 TTL/reorder/fallback gate 过滤。证据: `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:848`, `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:1002`, `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:1051`, `Gateway/main.py:11940`。
  8. Quest HUD 拉取 `/api/assets/{asset_id}` 并渲染 overlay；语音/触觉模块输出反馈；终端再回发 ack。证据: `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs:425`, `Assets/BeYourEyes/Presenters/Audio/SpeechOrchestrator.cs:203`, `Assets/BeYourEyes/Unity/Interaction/LocalSafetyFallback.cs:269`, `Gateway/main.py:3075`。
- 如果有多个版本，当前主用哪个:
  - 当前“最像作者正在主推的 Quest 路径”是 `BYES.*` smoke 线: `ByesQuest3ConnectionPanelMinimal` + `GatewayClient` + `ScanController` + `ByesVisionHud*` + `ByesHandMenuController`。
  - 旧路径仍存在: `AppBootstrap` + `GatewayWsClient` + `GatewayPoller` + `AppServices` bus。证据: `Assets/BeYourEyes/AppBootstrap.cs:78`, `Assets/Scenes/Quest3SmokeScene.unity:2207`。
  - 规划执行器也存在，但不在当前 Quest smoke 主场景显式出现。证据: `Quest3SmokeScene` 中找到 `ByesQuest3ConnectionPanelMinimal`/`ByesQuest3SelfTestRunner`，未找到 `PlanClient`/`PlanExecutor`/`ActionPlanExecutor`；而 `ByesRuntimeBootstrap` 只会在它们存在时做自动连线。证据: `Assets/Scripts/BYES/Core/ByesRuntimeBootstrap.cs:60`, `Assets/Scripts/BYES/Core/ByesRuntimeBootstrap.cs:70`。
  - 旧的 `ByesWristMenuController` 被新的 `ByesHandMenuController` 主动禁用，应视为遗留 UI。证据: `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs:126`, `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs:1646`。

## 3. 系统架构重建
- 文字描述:
  - 本地前端是 Unity/Quest 客户端，负责相机帧采集、模式切换、手势/控制器输入、WebSocket 事件接收、HUD/overlay 渲染、TTS/haptic 输出、本地 fallback。
  - 中央后端是 `Gateway/main.py`，负责接收帧、维护 frame/asset/run-package、执行调度、调用后端 provider、发出事件、提供 plan/record/assist/assets 接口。
  - 右侧模型层既包含 Gateway 进程内 provider，也包含通过 HTTP 调用的 `inference_service`、`planner_service`、`sam3_seg_service`、`da3_depth_service`、`reference_slam_service`、`pyslam_service` 等。
  - 底部是 run-package 工具链，负责记录、回放、报告、回归、benchmark、ablation。
- ASCII 图:

```text
[Quest / Unity local]
  ByesHandMenuController / ConnectionPanel / ScanController
    -> ByesPcaFrameSource / RenderTexture fallback
    -> GatewayClient or GatewayFrameUploader
    -- HTTP /api/frame, /api/assist, /api/mode, /api/record/* -->

                        [Gateway/main.py]
  /api/frame -> FrameCache + RecordingManager + scheduler.submit_frame
                                  -> _run_inference_for_frame(...)
                                  -> emits byes.event.v1 / assets / ws rows
  /api/assist -> reuse cached frame -> forceTargets/prompt -> resubmit
  /api/plan   -> plan_pipeline -> planner backend/service
  /ws/events  -> Unity
  /api/assets/{id} -> Unity HUD fetch

              [Provider / Service layer]
  OCR: paddleocr / tesseract / http / mock
  DET: ultralytics / yolo26 / mock
  RISK: reference / heuristic / http / mock
  SEG: http SAM3 / mock
  DEPTH: onnx / http / DA3 / mock
  SLAM: mock / http / reference_slam_service / pyslam_service
  PLAN: reference / llm / pov

[Quest feedback local]
  GatewayClient (WS)
    -> EventGuard + LocalActionPlanGate + LocalSafetyFallback
    -> ByesVisionHudRenderer (/api/assets/{id})
    -> SpeechOrchestrator / Haptics / FrameTelemetry ack

[Offline / evaluation]
  RecordingManager -> run package
  report_run.py / run_regression_suite.py / run_dataset_benchmark.py / eval_slam_tum.py
```

- 前端/后端边界:
  - 前端: `Assets/BeYourEyes/*`, `Assets/Scripts/BYES/*`
  - 后端: `Gateway/main.py`, `Gateway/byes/*`
- 通信边界:
  - HTTP: `/api/frame`, `/api/assist`, `/api/mode`, `/api/asr`, `/api/record/*`, `/api/plan`, `/api/assets/{id}`
  - WebSocket: `/ws/events`
- 同步/异步边界:
  - Unity 侧 capture、HTTP 请求、asset 获取、TTS/feedback 均以 coroutine/event 方式异步处理。
  - Gateway 侧 scheduler 有 FAST/SLOW 双队列与 worker；同时 direct inference-v1 路径是另一路异步流程。
  - 独立服务调用通过 HTTP，天然跨进程异步。
- 本地/云端边界:
  - 本地已确认: 帧采集、HUD、TTS/haptic、本地 fallback、事件过滤、手势 UI。
  - “边/云”仅能保守写成架构支持。repo 中确有 HTTP provider 与独立服务，但没有代码证据证明某个固定部署切分已经被系统性验证。
- fallback / degrade mode:
  - 客户端: `LocalSafetyFallback`, `LocalActionPlanGate`, `EventGuard`
  - 后端: scheduler TTL/cancel/preempt、planner fallback、provider truth/override、safe mode/degraded path

## 4. 模块级事实审计
### 4.1 帧采集与上传
- 状态: Implemented
- 代码证据:
  - 帧采集控制: `Assets/BeYourEyes/Unity/Interaction/ScanController.cs:15`, `Assets/BeYourEyes/Unity/Interaction/ScanController.cs:402`
  - 主帧源接口: `Assets/Scripts/BYES/Quest/ByesPcaFrameSource.cs:13`
  - PCA/fallback truth: `Assets/Scripts/BYES/Quest/ByesPcaFrameSource.cs:15`, `Assets/Scripts/BYES/Quest/ByesPcaFrameSource.cs:17`, `Assets/Scripts/BYES/Quest/ByesPcaFrameSource.cs:18`, `Assets/Scripts/BYES/Quest/ByesPcaFrameSource.cs:739`
  - 上传: `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs:301`, `Assets/BeYourEyes/Adapters/Networking/GatewayFrameUploader.cs:17`, `Gateway/main.py:2907`
- 输入输出:
  - 输入: Quest 相机/PCA 帧或 fallback 帧，附带 capture/meta/source-truth。
  - 输出: `/api/frame` multipart 请求，后端 frame cache、recording、inference 触发。
- 上游/下游依赖:
  - 上游: `ByesHandMenuController`, `ByesQuest3ConnectionPanelMinimal`, live loop/manual trigger。
  - 下游: `Gateway/main.py` 的 frame ingest、scheduler、recording。
- 当前完成度:
  - 主链中真实使用。
  - 具有 source-truth 标注，能区分 `pca_real`、`ar_cpuimage_fallback`、`rendertexture_fallback`、`unavailable`。
- 风险与缺口:
  - 代码存在但本次未做 Quest 实机运行验证。
  - PCA 真正可运行仍依赖设备、权限、ARFoundation 子系统与外部环境。

### 4.2 检测 / 查找 / 目标跟踪（含 prompt-conditioned find）
- 状态: Partially Implemented
- 代码证据:
  - Quest 端 find/assist 入口: `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs:1551`, `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs:2063`
  - 扫描 meta 中传 `targets`/`prompt`: `Assets/BeYourEyes/Unity/Interaction/ScanController.cs:867`, `Assets/BeYourEyes/Unity/Interaction/ScanController.cs:873`
  - 后端 assist 构造 `openVocab` prompt: `Gateway/main.py:4814`, `Gateway/main.py:4824`, `Gateway/main.py:4827`
  - 检测结果事件: `Gateway/main.py:1710`, `Gateway/main.py:7813`, `Gateway/main.py:7841`
  - Ultralytics provider prompt label 提取与 `set_classes`: `Gateway/services/inference_service/providers/ultralytics_det.py:126`, `Gateway/services/inference_service/providers/ultralytics_det.py:153`, `Gateway/services/inference_service/providers/ultralytics_det.py:175`, `Gateway/services/inference_service/providers/ultralytics_det.py:179`
  - Target tracking session/update: `Gateway/byes/target_tracking/store.py:32`, `Gateway/byes/target_tracking/manager.py:8`, `Gateway/byes/target_tracking/manager.py:78`, `Gateway/main.py:4889`, `Gateway/main.py:4907`
- 输入输出:
  - 输入: 当前或缓存帧，`targets=["det"]`，可选 `prompt.text`，可选 target session/ROI。
  - 输出: `det.objects.v1`、`target.session`、`target.update`、HUD 文本与 overlay。
- 上游/下游依赖:
  - 上游: 手势菜单、smoke panel、“find concept”、track start/step/stop。
  - 下游: `ByesVisionHudRenderer`, `ByesQuest3ConnectionPanelMinimal` 文本状态，`ByesGuidanceEngine`。
- 当前完成度:
  - 检测与 target session 路径真实存在，并进入 Quest smoke 主链。
  - 但“开放词汇检测”只看到 prompt-conditioned class filtering / target filtering，不足以证明成熟 open-vocabulary detection 方法。
- 风险与缺口:
  - 不能写成 YOLO-World/SAM 类方法已经在主系统中稳定复现。
  - 具体检测质量、开放词汇泛化能力、跟踪鲁棒性未在 repo 中找到论文级结果。

### 4.3 OCR / 文本读取
- 状态: Implemented
- 代码证据:
  - 后端 OCR 触发: `Gateway/main.py:1581`
  - 推理服务 OCR 端点: `Gateway/services/inference_service/app.py:388`
  - OCR provider 工厂: `Gateway/services/inference_service/providers/__init__.py:31`
  - PaddleOCR 本地 provider: `Gateway/services/inference_service/providers/paddleocr_ocr.py:43`, `Gateway/services/inference_service/providers/paddleocr_ocr.py:56`, `Gateway/services/inference_service/providers/paddleocr_ocr.py:71`
  - Quest 端 read/ocr assist: `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs:2024`
- 输入输出:
  - 输入: 图像帧，可选 target/prompt。
  - 输出: OCR 结果事件、文字播报、报告指标。
- 上游/下游依赖:
  - 上游: `read_text` 模式、assist、手势菜单。
  - 下游: `SpeechOrchestrator`, report/benchmark。
- 当前完成度:
  - OCR 是当前最实的能力之一；provider 抽象、本地 provider、报告与测试都存在。
- 风险与缺口:
  - “屏幕内容理解”超出 OCR 本身的语义解析能力，[未在 repo 中找到证据]。
  - OCR 真实效果依赖模型安装与权重；本次未运行验证。

### 4.4 风险/障碍感知
- 状态: Implemented
- 代码证据:
  - 后端 risk 触发: `Gateway/main.py:1628`
  - scheduler fast lane / critical preempt: `Gateway/byes/scheduler.py:239`, `Gateway/byes/scheduler.py:852`, `Gateway/byes/scheduler.py:906`
  - SafetyKernel guardrails: `Gateway/byes/safety_kernel.py:24`
  - Quest 本地风险播报: `Assets/BeYourEyes/Presenters/Audio/SpeechOrchestrator.cs:229`, `Assets/BeYourEyes/Presenters/Audio/SpeechOrchestrator.cs:247`
  - Local fallback state机: `Assets/BeYourEyes/Unity/Interaction/LocalSafetyFallback.cs:8`, `Assets/BeYourEyes/Unity/Interaction/LocalSafetyFallback.cs:94`
- 输入输出:
  - 输入: 帧、risk backend 输出、health/degrade 状态。
  - 输出: `risk.*` 事件、critical stop/confirm guardrail、TTS/haptic、安全 UI 状态。
- 上游/下游依赖:
  - 上游: frame ingest, scheduler, direct inference。
  - 下游: Speech/HUD/local gate/planner。
- 当前完成度:
  - 风险感知与安全播报/阻断路径是真实主链能力。
- 风险与缺口:
  - 不能把“安全有效”写成结果；缺少真实用户/场景验证、误报漏报统计与长期鲁棒性结果。

### 4.5 占据/代价地图（costmap）
- 状态: Partially Implemented
- 代码证据:
  - `CostmapFuser`: `Gateway/byes/mapping/costmap_fuser.py:36`
  - Gateway 中 costmap 事件发射: `Gateway/main.py:2043`, `Gateway/main.py:2088`, `Gateway/main.py:2130`
  - 报告/benchmark 指标: `Gateway/scripts/run_dataset_benchmark.py:73`, `Gateway/scripts/run_dataset_benchmark.py:78`
- 输入输出:
  - 输入: depth/seg/slam payload，可选动态 mask/tracking 信息。
  - 输出: `map.costmap`、`map.costmap_fused`、`map.costmap_context`。
- 上游/下游依赖:
  - 上游: depth, seg, slam。
  - 下游: planner context、report/benchmark。
- 当前完成度:
  - 后端算法与评测侧实现明显存在。
  - 但当前 Quest smoke 端未看到专门消费 costmap 的用户界面主链。
- 风险与缺口:
  - 可以写成“后端已有代价地图与融合实现”；不能写成“已形成用户可见的导航栅格闭环”。

### 4.6 深度估计
- 状态: Implemented
- 代码证据:
  - 后端 depth 触发与 depth map 事件: `Gateway/main.py:1726`, `Gateway/main.py:1772`, `Gateway/main.py:7956`
  - 推理服务 depth 端点: `Gateway/services/inference_service/app.py:715`
  - 本地 ONNX depth: `Gateway/services/inference_service/providers/onnx_depth.py:94`
  - 外部 DA3 深度服务: `Gateway/services/da3_depth_service/app.py:26`, `Gateway/services/da3_depth_service/app.py:247`
  - Quest HUD depth overlay: `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs:213`
- 输入输出:
  - 输入: 图像帧。
  - 输出: `depth.map.v1`、报告中的 depth 指标、可选 risk fused。
- 上游/下游依赖:
  - 上游: frame ingest。
  - 下游: risk fusion, HUD overlay, costmap。
- 当前完成度:
  - 深度能力在后端、独立服务、测试、报告链条中都是真实存在的。
- 风险与缺口:
  - “实时准确深度估计”仍需实验。
  - DA3 路径是独立服务，不是 repo 内原生深度算法。

### 4.7 3D 建图 / SLAM
- 状态: Partially Implemented
- 代码证据:
  - Gateway direct SLAM path 与事件: `Gateway/main.py:1920`, `Gateway/main.py:1963`, `Gateway/main.py:8007`
  - 推理服务 SLAM 端点: `Gateway/services/inference_service/app.py:791`
  - reference slam service: `Gateway/services/reference_slam_service/app.py:28`, `Gateway/services/reference_slam_service/app.py:224`
  - pySLAM proxy service: `Gateway/services/pyslam_service/app.py:39`, `Gateway/services/pyslam_service/app.py:55`
  - TUM 评测脚本: `Gateway/scripts/eval_slam_tum.py`, `Gateway/scripts/run_pyslam_on_run_package.py`
- 输入输出:
  - 输入: 图像帧，可选 pose/targets/prompt。
  - 输出: `slam.pose.v1`、`slam.trajectory.v1`、TUM 轨迹评测指标。
- 上游/下游依赖:
  - 上游: frame ingest, optional external service.
  - 下游: costmap, planner context, report。
- 当前完成度:
  - “SLAM pose 接口 + 代理/参考服务 + 评测管线”明确存在。
  - 但 repo 内未见成熟原生 SLAM 主算法；主路径主要是 mock/http/reference/pyslam proxy。
- 风险与缺口:
  - 不能把当前 repo 写成“完整 3D 建图系统已稳定服务用户”。
  - 只能保守写为“SLAM pose/trajectory integration and evaluation hooks”。

### 4.8 手部输入 / 手眼协调
- 状态: Partially Implemented
- 代码证据:
  - XR hand subsystem guard: `Assets/Scripts/BYES/XR/ByesXrSubsystemGuards.cs:36`
  - 手腕锚点与 palm-up 菜单: `Assets/Scripts/BYES/XR/ByesWristMenuAnchor.cs:82`, `Assets/Scripts/BYES/XR/ByesWristMenuAnchor.cs:115`
  - 手势快捷操作: `Assets/Scripts/BYES/XR/ByesHandGestureShortcuts.cs:116`, `Assets/Scripts/BYES/XR/ByesHandGestureShortcuts.cs:233`
  - 新手势菜单控制器: `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs:188`
- 输入输出:
  - 输入: XR hand joints, palm orientation, pinch/gesture/controller buttons。
  - 输出: 菜单开关、模式切换、find/read/record 等 UI 指令。
- 上游/下游依赖:
  - 上游: XR Hands / XR input subsystem。
  - 下游: `ByesQuest3ConnectionPanelMinimal` 方法调用。
- 当前完成度:
  - “手部输入用于 UI/菜单交互”是真实现。
  - “手眼协调 assistive control loop”[未在 repo 中找到证据]。
- 风险与缺口:
  - 不能把这一部分写成成熟 hand-eye coordination 研究贡献。
  - 最多写成 “hand-based interaction layer for the Quest prototype”。

### 4.9 主动感知 / POV / 视角规划
- 状态: Partially Implemented
- 代码证据:
  - POV context API: `Gateway/main.py:5407`
  - plan pipeline 读取 POV/seg/slam/costmap 上下文: `Gateway/byes/plan_pipeline.py:10`, `Gateway/byes/plan_pipeline.py:109`
  - planner `pov` provider 与 adapter: `Gateway/services/planner_service/app.py:621`, `Gateway/services/planner_service/pov_adapter.py:36`
- 输入输出:
  - 输入: run package 中的 POV IR、上下文 budget、planner request。
  - 输出: POV context pack、由 POV adapter 生成的 action plan。
- 上游/下游依赖:
  - 上游: run-package / POV IR。
  - 下游: `/api/plan`, report metrics。
- 当前完成度:
  - POV/active context 在后端与评测/规划侧存在。
  - 实时摄像头驱动的“主动转头/视角规划/相机控制闭环”[未在 repo 中找到主链证据]。
- 风险与缺口:
  - 不应把 active perception 写成已在 Quest 运行的用户功能。
  - 更安全的说法是“POV-derived context and planning hooks”。

### 4.10 规划 / Agent / VLM / VLA
- 状态: Partially Implemented
- 代码证据:
  - Gateway `/api/plan`: `Gateway/main.py:5599`
  - plan pipeline: `Gateway/byes/plan_pipeline.py:251`
  - planner service reference/llm/pov: `Gateway/services/planner_service/app.py:377`, `Gateway/services/planner_service/app.py:495`, `Gateway/services/planner_service/app.py:592`, `Gateway/services/planner_service/app.py:577`, `Gateway/services/planner_service/app.py:579`
  - Unity plan client/executors: `Assets/Scripts/BYES/Plan/PlanClient.cs:11`, `Assets/Scripts/BYES/Plan/PlanClient.cs:95`, `Assets/Scripts/BYES/Plan/ActionPlanExecutor.cs:8`, `Assets/Scripts/BYES/Plan/PlanExecutor.cs:9`
  - 旧 slow-lane RealVlmTool: `Gateway/byes/tools/real_vlm.py:12`, `Gateway/main.py:934`
- 输入输出:
  - 输入: POV/seg/slam/costmap context、risk summary、constraints、可选 LLM endpoint。
  - 输出: `byes.action_plan.v1`、confirm/action events、report rows。
- 上游/下游依赖:
  - 上游: run package contexts 或 Gateway current state。
  - 下游: `ActionPlanExecutor`, confirm UI, safety kernel。
- 当前完成度:
  - 规划后端是实代码，不是只在文档里。
  - 但当前 Quest smoke 场景未看到 `PlanClient`/`PlanExecutor`/`ActionPlanExecutor` 进入主场景主链；因此“LLM/VLM 驱动主工作流”不能强写。
- 风险与缺口:
  - `llm` provider 依赖外部 API/endpoint；`RealVlmTool` 同样依赖外部 URL。
  - “VLA control”[未在 repo 中找到证据]。

### 4.11 Unity UI / HUD / 模式切换 / 反馈
- 状态: Implemented
- 代码证据:
  - Quest smoke 主面板: `Assets/Scenes/Quest3SmokeScene.unity:2508`
  - 模式切换: `Assets/Scripts/BYES/Core/ByesModeManager.cs:8`
  - 手势菜单: `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs:20`
  - HUD overlay: `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs:167`, `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs:425`
  - Passthrough 控制: `Assets/Scripts/BYES/Quest/ByesPassthroughController.cs:7`, `Assets/Scripts/BYES/Quest/ByesPassthroughController.cs:40`
  - Guidance engine: `Assets/Scripts/BYES/Guidance/ByesGuidanceEngine.cs:31`
- 输入输出:
  - 输入: gateway events、target updates、mode state、hand/controller input。
  - 输出: 文本 UI、overlay、passthrough、简易 guidance、toast。
- 上游/下游依赖:
  - 上游: GatewayClient、手势菜单、Quest scene。
  - 下游: TTS/haptic/ack。
- 当前完成度:
  - Quest 端 UI/HUD/模式切换是真实现，不是草图。
  - Guidance 是简单启发式方向提示，不是完整导航规划器。
- 风险与缺口:
  - 不能把 HUD/UI 写成已经做过用户体验研究。
  - Passthrough 运行仍依赖 Quest 设备、ARFoundation 与权限。

### 4.12 语音 I/O
- 状态: Partially Implemented
- 代码证据:
  - TTS orchestration: `Assets/BeYourEyes/Presenters/Audio/SpeechOrchestrator.cs:10`
  - `/api/asr` 后端: `Gateway/main.py:4662`
  - Quest panel 触发 ASR: `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs:3725`
- 输入输出:
  - 输入: gateway risk/action/confirm/dialog 事件，或音频上传。
  - 输出: TTS 播报，ASR 文本返回。
- 上游/下游依赖:
  - 上游: Gateway event stream / 麦克风音频。
  - 下游: 语音闭环交互。
- 当前完成度:
  - TTS 输出明确存在。
  - ASR 入口存在，但具体 ASR backend 与完整“语音代理闭环”仍依赖外部资源。
- 风险与缺口:
  - 不能写成完整 voice assistant 已验证。

### 4.13 日志 / 监控 / 可观测性 / 录制
- 状态: Implemented
- 代码证据:
  - RecordingManager: `Gateway/byes/recording/manager.py:61`, `Gateway/byes/recording/manager.py:80`, `Gateway/byes/recording/manager.py:189`, `Gateway/byes/recording/manager.py:223`
  - `/api/record/start` / `/api/record/stop`: `Gateway/main.py:4929`, `Gateway/main.py:4953`
  - report_run / regression / benchmark: `Gateway/scripts/report_run.py:922`, `Gateway/scripts/run_regression_suite.py`, `Gateway/scripts/run_dataset_benchmark.py:1074`
  - CI 合同与回归: `.github/workflows/gateway-ci.yml:36`, `.github/workflows/gateway-ci.yml:44`, `.github/workflows/gateway-ci.yml:52`
- 输入输出:
  - 输入: frame、event、asset、metrics、ground truth。
  - 输出: run package、report、benchmark CSV/JSON/MD、回归判定。
- 上游/下游依赖:
  - 上游: Gateway runtime, Unity ack/record triggers。
  - 下游: 论文实验与分析。
- 当前完成度:
  - 这是仓库最成熟的部分之一。
- 风险与缺口:
  - 已有 run packages 与 reports 说明工具链被使用过，但这些工件本身不是论文结果，仍需筛选与正式统计。

### 4.14 安全 / 拒答 / 隐私策略
- 状态: Partially Implemented
- 代码证据:
  - 本地 fallback: `Assets/BeYourEyes/Unity/Interaction/LocalSafetyFallback.cs:8`
  - 本地 action gate: `Assets/BeYourEyes/Adapters/Networking/LocalActionPlanGate.cs:7`
  - Planner safety kernel: `Gateway/byes/safety_kernel.py:24`
  - API key guard: `Gateway/main.py:2715`, `Gateway/main.py:2822`, `Gateway/tests/test_gateway_api_key_http.py:18`
  - Dev endpoint hardening: `Gateway/tests/test_gateway_dev_endpoints_toggle.py:29`
- 输入输出:
  - 输入: risk level, health status, confirm state, HTTP headers/env toggles。
  - 输出: stop/confirm guardrail、fallback speech/haptic、接口 401/403/404。
- 上游/下游依赖:
  - 上游: risk planner, gateway config。
  - 下游: Unity feedback, API access control。
- 当前完成度:
  - runtime safety guardrails 与 API guards 有真实代码。
  - 系统化隐私脱敏、数据最小化、PII redaction、合规策略 [未在 repo 中找到证据]。
- 风险与缺口:
  - 论文里不能把这部分写成完整 privacy/security framework。

## 5. 算法 / 模型 / 服务证据表
| 名称 | 类型 | 在 repo 中的证据 | 是否进入主链 | 当前角色 | 备注 |
| --- | --- | --- | --- | --- | --- |
| `Gateway Scheduler` | 传统系统调度 | `Gateway/byes/scheduler.py`, `FAST/SLOW queue`, TTL, preempt | Yes | 后端异步调度 | 与 direct inference-v1 并存 |
| `FrameCache` | 系统缓存 | `Gateway/main.py:777`, `Gateway/byes/frame_cache.py:28` | Yes | assist/重提交流程 | 被 `/api/assist` 复用 |
| `AssetCache` | 系统缓存 | `Gateway/main.py:781`, `Gateway/byes/asset_cache.py:31` | Yes | overlay asset 缓存 | Quest HUD 拉取 asset |
| `PaddleOCR` provider | 本地模型 | `paddleocr_ocr.py:56`, `paddleocr_ocr.py:71` | Optional | OCR backend | 需安装可选依赖 |
| `Ultralytics / YOLO26` provider | 本地模型 | `ultralytics_det.py:110`, `yolo26_det.py:7` | Optional | 检测 backend | 非 repo 自研检测算法 |
| prompt-conditioned DET filtering | wrapper/适配逻辑 | `ultralytics_det.py:126`, `ultralytics_det.py:153` | Yes | find concept / open-vocab-like path | 只能保守写 |
| `reference / heuristic risk` | 传统算法 | `reference_risk.py`, `heuristic_risk.py` | Optional | 风险评估 | provider 由配置决定 |
| `HttpSegProvider` | 外部 API wrapper | `http_seg.py:17` | Optional | 分割代理 | 对接外部 `/seg` 服务 |
| `sam3_seg_service` | 独立服务 | `Gateway/services/sam3_seg_service/app.py:26`, `Gateway/services/sam3_seg_service/app.py:316` | Optional | 外部分割服务 | 不是 Gateway 内原生实现 |
| `onnx_depth` | 本地模型 | `onnx_depth.py:94` | Optional | 深度 backend | 依赖 `onnxruntime` |
| `da3_depth_service` | 独立服务 | `Gateway/services/da3_depth_service/app.py:26`, `Gateway/services/da3_depth_service/app.py:247` | Optional | 外部深度服务 | 通过 HTTP 接入 |
| `MockSlamProvider` / `HttpSlamProvider` | mock / 外部 API wrapper | `mock_slam.py:8`, `http_slam.py:17` | Optional | SLAM pose 接口 | 主线可发 `slam.pose.v1` |
| `reference_slam_service` | 独立服务 | `reference_slam_service/app.py:28`, `reference_slam_service/app.py:224` | Optional | 参考 SLAM 服务 | 不是用户侧完整 mapping 证据 |
| `pyslam_service` | 独立服务/proxy | `pyslam_service/app.py:39`, `pyslam_service/app.py:55` | Optional | pySLAM 代理接口 | 主要用于离线/服务集成 |
| `CostmapFuser` | 传统算法 | `Gateway/byes/mapping/costmap_fuser.py:36` | Optional | costmap 融合 | 后端已有，UI 主链弱 |
| `planner_service reference` | 传统规划器 | `planner_service/app.py:377` | Optional | 规则/参考 plan | `/api/plan` 后端路径真实存在 |
| `planner_service llm` | 外部 API wrapper | `planner_service/app.py:495`, `planner_service/app.py:515` | Optional | LLM planning | 依赖外部 endpoint/API |
| `planner_service pov` | 适配器 | `planner_service/app.py:621`, `pov_adapter.py:36` | Optional | POV IR -> action plan | 更像 compiler/adapter |
| `RealVlmTool` | 外部 API wrapper | `real_vlm.py:12`, `Gateway/main.py:934` | Legacy/Optional | 旧 scheduler slow-lane VLM | 当前 Quest smoke 主链不清晰 |

## 6. 数据流、控制流与时序
- 一帧/一次请求如何流动:
  1. 用户在 Quest 端触发 `scan/read/find/track`。证据: `ByesHandMenuController.cs:369`, `ByesQuest3ConnectionPanelMinimal.cs:2063`。
  2. `ScanController` 调 `IByesFrameSource` 抓图，填充 `capture` 与 `frameSource` 元数据。证据: `ScanController.cs:402`, `ScanController.cs:403`, `ScanController.cs:405`。
  3. 帧经 `/api/frame` 上传，Gateway 同步解析文件与 `meta`。证据: `GatewayClient.cs:657`, `Gateway/main.py:2907`。
  4. Gateway 记录 `frame.input`，写 `FrameCache`，可选写 recording。证据: `Gateway/main.py:3039`, `Gateway/byes/recording/manager.py:189`。
  5. Gateway 把帧送入 scheduler，同时直接调用 `_run_inference_for_frame`。证据: `Gateway/main.py:2175`, `Gateway/main.py:2185`。
  6. 根据 mode/forcedTargets 决定本帧是否跑 OCR/RISK/DET/DEPTH/SEG/SLAM。证据: `Gateway/byes/scheduler.py:1081`, `Gateway/main.py:1570`, `Gateway/main.py:2006`。
  7. 推理结果进入 `byes.event.v1` 队列，并可产出 overlay asset。证据: `Gateway/main.py:1334`, `Gateway/main.py:1710`, `Gateway/main.py:1772`, `Gateway/main.py:1900`, `Gateway/main.py:1963`。
  8. Quest 端 `GatewayClient` 从 `/ws/events` 收包，先过 `LocalActionPlanGate` 和 `EventGuard`。证据: `GatewayClient.cs:1002`, `GatewayClient.cs:1051`。
  9. HUD 拉取 `/api/assets/{asset_id}` 并渲染 `seg.mask.v1` / `depth.map.v1` / `det.objects.v1` / `target.update`。证据: `ByesVisionHudRenderer.cs:187`, `ByesVisionHudRenderer.cs:425`。
  10. 语音与触觉模块输出反馈，并通过 `/api/frame/ack` 回写用户侧 e2e 统计。证据: `SpeechOrchestrator.cs:166`, `Gateway/main.py:3075`。
- 哪些地方是异步:
  - Unity coroutines: capture/upload/asset-fetch/asr/record/assist。
  - Gateway scheduler: FAST/SLOW 双 worker 异步。
  - WebSocket: Unity `GatewayClient` 与旧 `GatewayWsClient` 均异步收包。
  - 服务间调用: inference/planner/sam3/da3/slam 多为 HTTP 异步依赖。
- 哪些地方可能成为延迟瓶颈:
  - Quest 端 GPU readback / PCA capture fallback。
  - `/api/frame` 上传与图片压缩。
  - 外部 HTTP provider: OCR/SEG/DEPTH/SLAM/LLM。
  - overlay asset 二次下载 `/api/assets/{id}`。
  - LLM planner 与 `RealVlmTool`。
- 哪些地方有缓存/降级/重试:
  - `FrameCache`/`AssetCache`。
  - `/api/assist` 对 cached frame 的重提交。
  - `EventGuard` TTL + reorder guard。
  - `LocalSafetyFallback` 的 `OK/STALE/DISCONNECTED/SAFE_MODE_REMOTE`。
  - `LocalActionPlanGate` 的 block/patch。
  - scheduler 的 TTL drop、cancel older frames、preempt window、slow queue drop。
  - planner_service 的 `fallbackUsed` / `fallbackReason`。
  - `GatewayClient`/`GatewayWsClient` 的 WS 重连与 health 探测。
- 特别说明:
  - 当前 repo 中“旧 scheduler/tool-registry 线路”和“新 direct inference-v1 线路”是并存的，而不是已经完成一次性重构收敛。

## 7. 实验与可复现性审计
- 是否有训练脚本:
  - 本次对 `Gateway` 与 `Assets` 进行了文件名级搜索（`train|trainer|training|checkpoint|checkpoints|fit|epoch`），未发现明确训练入口脚本或 checkpoint 管理目录。
  - 结论: 训练代码 [未在 repo 中找到证据]。
- 是否有推理脚本:
  - 有。`Gateway/main.py`、`services/inference_service/app.py`、`services/planner_service/app.py`、`services/pyslam_service/app.py` 都是运行入口。
- 是否有 benchmark:
  - 有。证据: `Gateway/scripts/run_dataset_benchmark.py:1074`, `Gateway/scripts/eval_slam_tum.py`, `Gateway/scripts/bench_risk_latency.py`。
- 是否有 latency / user study / ablation:
  - latency: 有脚本与报告抽取。证据: `Gateway/scripts/bench_risk_latency.py`, `Gateway/scripts/report_run.py:1107`。
  - ablation: 有脚本。证据: `Gateway/scripts/ablate_planner.py`, `Gateway/scripts/sweep_depth_input_size.py`, `Gateway/scripts/sweep_seg_prompt_budget.py`, `Gateway/scripts/sweep_plan_context_pack.py`。
  - user study: [未在 repo 中找到证据]。
- 是否能端到端运行:
  - 代码层面具备端到端入口与 run-package 录制链路。
  - 但本次审计未安装重依赖、未做 Quest 实机验证、未拉起外部模型服务，故只能写“代码存在但可运行性未验证”。
- 固定测试/夹具证据:
  - `Gateway/tests/fixtures/` 下有大量最小 run-package 夹具，包括 OCR、seg、depth、slam、SAM3、DA3、plan、POV、costmap。
  - `Gateway/artifacts/run_packages/` 下已有大量历史 run-package 工件，说明工具链被实际使用过。
- CI 与回归:
  - Pytest、lint run package、baseline/contract regression、contracts lock 都进了 CI。证据: `.github/workflows/gateway-ci.yml:36`, `.github/workflows/gateway-ci.yml:40`, `.github/workflows/gateway-ci.yml:44`, `.github/workflows/gateway-ci.yml:52`。
- 可复现性判断: Medium
- 原因:
  - 高于低可复现: 因为接口、夹具、报告、合同、回归、独立服务入口都在 repo 中。
  - 低于高可复现: 因为 Quest 实机、模型权重、外部 API/HTTP 服务、可选依赖安装与真实部署拓扑都不完全封装在 repo 内。

## 8. 代码现实 vs 设计目标
| 设计目标 | repo 证据 | 当前结论 | 论文写法建议 |
| --- | --- | --- | --- |
| MR/Unity 前端 | `Quest3SmokeScene`, `ByesQuest3ConnectionPanelMinimal`, `ScanController`, `GatewayClient` | 已有真实前端原型 | 可直接写 |
| WebSocket + HTTP 通信层 | `Gateway/main.py:2907`, `Gateway/main.py:11940`, `GatewayClient.cs:657` | 已实现 | 可直接写 |
| 端边云协同 | 多 HTTP provider/service + Quest 本地 fallback + Gateway 聚合 | 架构支持存在 | 需保守表述 |
| 低延迟异步流水线 | FAST/SLOW scheduler, TTL, preempt, EventGuard, LocalSafetyFallback | 设计与实现存在 | 需保守表述 |
| 实时低延迟效果 | 只有脚本/指标抽取框架，当前未引用正式结果 | [待补结果] | 暂不应写成结果结论 |
| OCR / 文字读取 | OCR providers + Quest read flow | 已实现 | 可直接写 |
| 开放词汇检测 | prompt-conditioned DET + `set_classes` 尝试 | 仅部分实现 | 需保守表述 |
| 分割/SAM 类能力 | `HttpSegProvider` + `sam3_seg_service` + `seg.mask.v1` | 部分实现 | 需保守表述 |
| 风险/障碍感知 | risk backend + safety fallback + critical guardrail | 已实现 | 可直接写 |
| 占据/代价地图 | `CostmapFuser` + report metrics | 部分实现 | 需保守表述 |
| 深度估计 | onnx/http/DA3 depth + depth map events | 已实现 | 可直接写 |
| 3D 建图 / SLAM | slam pose 接口、reference/pyslam service、TUM 评测 | 部分实现 | 需保守表述 |
| 手眼协调 | 只有手部输入 UI/gesture 代码 | 设计目标未落到 assistive hand-eye 主链 | 暂不应写 |
| 主动感知 | POV context + planner adapter | 后端上下文/规划侧部分实现 | 需保守表述 |
| VLM/VLA 控制 | planner llm provider + RealVlmTool adapter | 存在代码，但非 Quest smoke 主链 | 暂不应写强 claim |
| 语音/视觉/声音闭环 | TTS + HUD + ASR endpoint + ack telemetry | 部分实现 | 需保守表述 |
| 可观测性 / 录制 / 回放 / 报告 | run-package / report / regression / benchmark | 已实现 | 可直接写 |
| 安全 / 降级 / 拒答 | local gate + safety kernel + API guards | 已有 runtime 层实现 | 可直接写“runtime safety guardrails”，不要扩写成完整安全框架 |

## 9. 论文可安全主张的贡献点
- 贡献点 1: 本仓库实现了一个 Quest/Unity 到 Python Gateway 的端到端辅助视觉原型，覆盖图像采集、后端事件生成、HUD/语音/触觉反馈和 user-side ack。
  - 证据: `ScanController.cs`, `GatewayClient.cs`, `Gateway/main.py:2907`, `Gateway/main.py:11940`, `ByesVisionHudRenderer.cs`, `SpeechOrchestrator.cs`
  - 安全级别: High
  - 建议措辞: “We implement an end-to-end Quest-to-Gateway assistive vision prototype with visual, speech, and haptic feedback hooks.”
- 贡献点 2: 系统具有模式感知的异步调度与安全降级机制，包括 FAST/SLOW lane、TTL、preempt、local fallback、action-plan gate。
  - 证据: `Gateway/byes/scheduler.py`, `Gateway/byes/safety_kernel.py`, `EventGuard.cs`, `LocalSafetyFallback.cs`, `LocalActionPlanGate.cs`
  - 安全级别: High
  - 建议措辞: “The prototype includes mode-aware asynchronous scheduling and runtime safety fallbacks on both the backend and the client.”
- 贡献点 3: 仓库提供了 run-package 为中心的记录、回放、报告、回归与合同测试基础设施，覆盖 perception、plan、latency 与 schema consistency。
  - 证据: `Gateway/byes/recording/manager.py`, `Gateway/scripts/report_run.py`, `Gateway/scripts/run_regression_suite.py`, `Gateway/scripts/run_dataset_benchmark.py`, `.github/workflows/gateway-ci.yml`
  - 安全级别: High
  - 建议措辞: “The system is instrumented with a run-package-based evaluation and regression workflow rather than only ad hoc demos.”
- 贡献点 4: 后端实现了多 provider 抽象，并显式区分 mock/reference/http/local/real/fallback truth state。
  - 证据: `Gateway/services/inference_service/providers/__init__.py`, `Gateway/main.py:3721`, `Gateway/main.py:4062`, `ByesPcaFrameSource.cs`, `ByesPassthroughController.cs`
  - 安全级别: High
  - 建议措辞: “The repository exposes provider truth and capability state explicitly, which makes the prototype auditable under mixed real/mock/fallback deployments.”
- 贡献点 5: 当前主链已经支持 OCR、检测/find、风险感知、深度、overlay 回传、target tracking 等可组合能力。
  - 证据: `Gateway/main.py:1553`, `Gateway/main.py:1710`, `Gateway/main.py:1772`, `Gateway/main.py:1900`, `Gateway/main.py:4889`, `Gateway/main.py:4907`
  - 安全级别: Medium
  - 建议措辞: “The current prototype already integrates multiple assistive perception modules in a shared event pipeline.”
- 贡献点 6: Quest 端存在手势/手部输入 UI 与 passthrough/HUD 交互层，用于辅助系统操作，而不是只在桌面端 demo。
  - 证据: `ByesHandMenuController.cs`, `ByesHandGestureShortcuts.cs`, `ByesPassthroughController.cs`
  - 安全级别: Medium
  - 建议措辞: “The prototype includes on-device interaction layers tailored for Quest hand/controller usage.”

## 10. 当前不能写或必须保守写的点
- 不能写: “本系统已经实现成熟的开放词汇检测/分割方法。”
  - 为什么不能写: 代码里有 prompt-conditioned DET/SEG 接口和外部服务 wrapper，但没有足够证据证明成熟的 open-vocabulary 方法性能或统一主链落地。
  - 最小补齐工作量: 固定 provider、跑标准 open-vocab benchmark、给出定量结果和失败案例。
- 不能写: “系统在 Quest 上实现了实时低延迟并显著优于 baseline。”
  - 为什么不能写: 当前 repo 只有 latency instrumentation 与 benchmark/report 脚本；没有可直接引用的正式实验结果。
  - 最小补齐工作量: 补真实硬件延迟表、P50/P90/P99、不同 provider 配置、和 baseline 比较。
- 不能写: “系统已实现完整 3D 建图/SLAM 导航闭环。”
  - 为什么不能写: 现有证据更像 SLAM pose/trajectory integration + service proxy + TUM evaluation hooks。
  - 最小补齐工作量: 明确主用 SLAM backend，给在线轨迹与用户任务效果，证明前端实际消费该能力。
- 不能写: “系统已实现主动感知/视角规划闭环。”
  - 为什么不能写: 当前 POV 代码主要在 run-package/context/planner 侧；未见实时相机控制或视角执行主链。
  - 最小补齐工作量: 加入在线 policy -> viewpoint action -> perception gain 的闭环与实验。
- 不能写: “系统已具备手眼协调能力。”
  - 为什么不能写: 手部代码主要用于菜单、gesture shortcuts、输入模式切换，不是 assistive hand-eye task logic。
  - 最小补齐工作量: 明确定义 hand-eye task，给出在线控制逻辑与实验。
- 不能写: “VLM/VLA 是当前 Quest 主工作流的核心控制器。”
  - 为什么不能写: planner/RealVlmTool 虽存在，但 Quest smoke 主场景未明确把 plan client/executors 接入主链。
  - 最小补齐工作量: 在主场景打通 `/api/plan` -> action execution -> confirm loop，并给结果。
- 必须保守写: “端边云协同”。
  - 为什么只能保守写: 架构支持明确存在，但没有系统性部署/性能/容错结果。
  - 最小补齐工作量: 给固定部署拓扑、服务边界、断网/降级实验。
- 必须保守写: “安全”。
  - 为什么只能保守写: 有 runtime guardrails，但没有用户安全结果、伦理评估或完整隐私策略。
  - 最小补齐工作量: 风险漏检/误报实验、human factors、隐私与合规说明。
- 不能写: “用户研究已经表明系统有效。”
  - 为什么不能写: [未在 repo 中找到证据]。
  - 最小补齐工作量: IRB/伦理说明、受试者设计、统计分析。

## 11. 最缺的实验、图、表和日志
- P0: Quest 真实端到端时延与失败率实验。
  - 为什么: 没有这个，不应把“低延迟实时辅助”写成结果。
  - 放置章节: `Experiments`
- P0: 固定 provider 配置下的核心任务结果表。
  - 内容: OCR、DET/find、risk、depth、seg、slam、frame-e2e。
  - 放置章节: `Experiments`
- P0: 主链开关/降级消融。
  - 内容: scheduler preempt on/off、EventGuard on/off、LocalSafetyFallback on/off、provider real/mock/fallback。
  - 放置章节: `Experiments` / `Low-Latency Co-Design`
- P0: 主场景真正使用的配置快照与 capability truth 记录。
  - 为什么: 当前仓库 provider 选择高度可配置，没有这个会导致实验不可复现。
  - 放置章节: `Implementation` / `Appendix`
- P1: 规划上下文与 safety kernel 消融。
  - 内容: pov/seg/slam/costmap context pack on/off；guardrails on/off；fallbackUsed rate。
  - 放置章节: `Experiments`
- P1: SLAM / costmap 质量评估。
  - 内容: TUM ATE/RPE、tracking rate、costmap fused stability/flicker/shift gate。
  - 放置章节: `Experiments`
- P1: 失败案例图集。
  - 内容: prompt-conditioned find 失败、seg mask 错误、depth 失败、SLAM lost、fallback 触发。
  - 放置章节: `Discussion / Limitation`
- P1: 长时稳定性日志。
  - 内容: reconnect、safe-mode enter、preempt count、throttle count、event drop rate。
  - 放置章节: `Experiments` / `Appendix`
- P2: 用户交互负担与 confirm/haptic 统计。
  - 放置章节: `Discussion`
- P2: 能耗、带宽、asset fetch 开销。
  - 放置章节: `Experiments` / `Appendix`

## 12. 适合论文的图表建议
- 系统总览图
  - 画什么: Quest 端采集/交互、Gateway、独立服务、run-package/report 管线。
  - 用 repo 里哪些内容画: `Quest3SmokeScene`, `ScanController`, `GatewayClient`, `Gateway/main.py`, `services/*`, `recording/manager.py`, `report_run.py`。
- 数据流/时序图
  - 画什么: `scan -> /api/frame -> scheduler + _run_inference_for_frame -> ws/assets -> HUD/TTS/haptic -> /api/frame/ack`。
  - 用 repo 里哪些内容画: `ScanController`, `Gateway/main.py`, `ByesVisionHudRenderer`, `SpeechOrchestrator`。
- 模块对照表
  - 画什么: 每个目标模块的 `Implemented / Partially Implemented / Documented but Not Implemented / Missing`。
  - 用 repo 里哪些内容画: 本审计第 4 节。
- 低延迟流水线图
  - 画什么: FAST/SLOW lane、TTL、cancel older frames、preempt window、EventGuard、LocalSafetyFallback。
  - 用 repo 里哪些内容画: `Gateway/byes/scheduler.py`, `EventGuard.cs`, `LocalSafetyFallback.cs`, `LocalActionPlanGate.cs`。
- 失败案例图
  - 画什么: OCR miss、find concept 错检、seg mask 漏、depth/SLAM unavailable、fallback overlay。
  - 用 repo 里哪些内容画: run-package fixtures + historical artifacts + overlay asset dumps。
- 消融表
  - 画什么: scheduler/preempt/fallback/plan context/safety kernel on-off。
  - 用 repo 里哪些内容画: `ablate_planner.py`, `sweep_plan_context_pack.py`, `run_dataset_benchmark.py`。
- 端到端性能表
  - 画什么: `riskLatencyP90`, `frame_e2e_p90`, OCR CER, seg F1, depth AbsRel, slam ATE/RPE, costmap stability。
  - 用 repo 里哪些内容画: `report_run.py`, `run_dataset_benchmark.py`, `eval_slam_tum.py`。

## 13. 论文写作建议
- 最适合的论文定位:
  - 系统论文 / prototype / 工程型 assistive AI systems paper。
  - 不建议定位为纯算法论文。
- 最稳妥的标题方向（3 个）:
  - `Be Your Eyes: A Quest-Based Assistive Vision Prototype with Auditable Runtime Feedback and Evaluation`
  - `Be Your Eyes: An End-to-End Assistive Vision System Prototype with Mode-Aware Scheduling and Run-Package Evaluation`
  - `Be Your Eyes: A Mixed Reality Assistive Perception Prototype with Safety Fallbacks and Multi-Provider Integration`
- 最适合的贡献组织方式（2 套）:
  - 套路 1: `System + Runtime`
    - 端到端 Quest-Gateway 原型
    - mode-aware async scheduling + safety fallback
    - multi-provider perception integration
    - run-package evaluation stack
  - 套路 2: `Prototype + Toolchain`
    - assistive interaction frontend
    - backend orchestration and capability truth
    - replay/report/regression infrastructure
    - preliminary module-level evaluation
- 最容易被审稿人攻击的点:
  - 系统结构过渡态明显，像“两个版本叠在一起”。
  - 没有正式结果就谈低延迟/安全/用户价值会被直接质疑。
  - active perception / hand-eye / VLM/VLA / SLAM 若写过头，极易被抓。
  - repo 的 provider 可选项很多，若实验配置不锁定，会被质疑不可复现。

## 14. Claim-Evidence Matrix（最重要）
| claim | evidence | confidence | can write now? | what is still missing? |
| --- | --- | --- | --- | --- |
| 仓库包含 Unity/Quest 前端原型 | `Quest3SmokeScene`, `ByesQuest3ConnectionPanelMinimal`, `ByesHandMenuController` | High | yes | 无 |
| `Quest3SmokeScene` 是当前构建主场景 | `ProjectSettings/EditorBuildSettings.asset:9` | High | yes | 无 |
| Quest 端可采集图像并上传 Gateway | `ScanController`, `ByesPcaFrameSource`, `/api/frame` | High | yes | 实机运行截图/日志可进一步增强 |
| 系统支持 WebSocket 事件回传 | `GatewayClient.HandleWsMessage`, `/ws/events` | High | yes | 无 |
| 系统支持 overlay asset 拉取与 Quest HUD 渲染 | `ByesVisionHudRenderer`, `/api/assets/{asset_id}` | High | yes | 可补运行截图 |
| Gateway 是统一后端聚合入口 | `Gateway/main.py` 中 `/api/frame`, `/api/assist`, `/api/plan`, `/api/record/*`, `/ws/events` | High | yes | 无 |
| 后端存在异步双队列调度 | `Gateway/byes/scheduler.py` FAST/SLOW 队列 | High | yes | 可补调度实验 |
| 后端还保留 direct inference-v1 路径 | `submit_frame -> scheduler.submit_frame -> _run_inference_for_frame` | High | yes | 无 |
| OCR 是真实集成能力 | `inference_service /ocr`, PaddleOCR provider, Quest read flow | High | yes | 正式结果 |
| 检测/find 路径是真实集成能力 | `/api/assist`, `UltralyticsDetProvider`, `det.objects.v1`, `target.update` | High | yes | 定量质量结果 |
| 开放词汇检测已经成熟落地 | 只有 prompt-conditioned class filtering 与 prompt metadata | Medium | no | 固定方法、标准 benchmark、结果 |
| 分割链路存在 | `http_seg`, `sam3_seg_service`, `seg.mask.v1` | Medium | careful | 主链配置与结果 |
| 深度链路存在 | `onnx_depth`, `da3_depth_service`, `depth.map.v1` | High | yes | 正式结果 |
| SLAM pose 集成存在 | `/slam/pose`, `reference_slam_service`, `pyslam_service`, `eval_slam_tum.py` | Medium | careful | 主用 backend、用户闭环结果 |
| costmap 与 fused costmap 已实现 | `CostmapFuser`, `map.costmap`, `map.costmap_fused` | Medium | careful | Quest 用户侧消费与结果 |
| 系统有 run-package 记录/回放/报告框架 | `RecordingManager`, `report_run.py`, `run_regression_suite.py` | High | yes | 无 |
| 系统有 runtime safety guardrails | `LocalSafetyFallback`, `LocalActionPlanGate`, `SafetyKernel` | High | yes | 用户安全实验 |
| 系统有 planner / action plan 后端 | `/api/plan`, `planner_service`, `PlanClient` | High | careful | 主场景实际接入与结果 |
| 当前 Quest smoke 场景默认使用 planner 主链 | 场景中未检出 `PlanClient`/`PlanExecutor`/`ActionPlanExecutor` | High | no | 主场景打通与验证 |
| 手部输入已用于 Quest UI | `ByesHandGestureShortcuts`, `ByesHandMenuController`, `ByesWristMenuAnchor` | High | yes | 无 |
| 手眼协调能力已落地 | 仅发现手部输入 UI，没有 assistive hand-eye task loop | Medium | no | 任务定义、控制逻辑、结果 |
| 主动感知已在线闭环运行 | POV/plan context 代码存在，但无在线 camera control 主链证据 | Medium | no | 在线主动感知实现与实验 |
| repo 含训练代码 | repo-wide search 未发现明确训练入口 | High | no | 训练代码或明确外部依赖说明 |
| repo 已包含用户研究结果 | 未在 repo 中找到用户研究或统计结果 | High | no | study protocol + data |

## 15. 附录：关键证据清单
- Unity 场景与引导:
  - `Assets/Scenes/Quest3SmokeScene.unity`
  - `Assets/BeYourEyes/AppBootstrap.cs`
  - `Assets/Scripts/BYES/Core/ByesRuntimeBootstrap.cs`
- Unity 主链组件:
  - `Assets/BeYourEyes/Unity/Interaction/ScanController.cs`
  - `Assets/Scripts/BYES/Quest/ByesPcaFrameSource.cs`
  - `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs`
  - `Assets/BeYourEyes/Adapters/Networking/GatewayFrameUploader.cs`
  - `Assets/Scripts/BYES/Quest/ByesQuest3ConnectionPanelMinimal.cs`
  - `Assets/Scripts/BYES/Quest/ByesHandMenuController.cs`
  - `Assets/Scripts/BYES/Quest/ByesVisionHudRenderer.cs`
  - `Assets/Scripts/BYES/Quest/ByesPassthroughController.cs`
  - `Assets/BeYourEyes/Presenters/Audio/SpeechOrchestrator.cs`
  - `Assets/BeYourEyes/Unity/Interaction/LocalSafetyFallback.cs`
  - `Assets/BeYourEyes/Adapters/Networking/LocalActionPlanGate.cs`
  - `Assets/BeYourEyes/Adapters/Networking/EventGuard.cs`
- Gateway 主链:
  - `Gateway/main.py`
  - `GatewayApp.submit_frame`
  - `GatewayApp._run_inference_for_frame`
  - `/api/frame`, `/api/assist`, `/api/plan`, `/api/record/start`, `/api/record/stop`, `/ws/events`
- Gateway 核心子模块:
  - `Gateway/byes/scheduler.py`
  - `Gateway/byes/safety_kernel.py`
  - `Gateway/byes/plan_pipeline.py`
  - `Gateway/byes/mapping/costmap_fuser.py`
  - `Gateway/byes/recording/manager.py`
  - `Gateway/byes/target_tracking/store.py`
  - `Gateway/byes/target_tracking/manager.py`
- 独立服务:
  - `Gateway/services/inference_service/app.py`
  - `Gateway/services/inference_service/providers/__init__.py`
  - `Gateway/services/planner_service/app.py`
  - `Gateway/services/planner_service/pov_adapter.py`
  - `Gateway/services/reference_slam_service/app.py`
  - `Gateway/services/pyslam_service/app.py`
  - `Gateway/services/sam3_seg_service/app.py`
  - `Gateway/services/da3_depth_service/app.py`
- 评测与报告:
  - `Gateway/scripts/report_run.py`
  - `Gateway/scripts/run_regression_suite.py`
  - `Gateway/scripts/run_dataset_benchmark.py`
  - `Gateway/scripts/eval_slam_tum.py`
  - `Gateway/tests/fixtures`
  - `Gateway/artifacts/run_packages`
