# PAPER_SOURCE_MARKDOWN_FOR_BE_YOUR_EYES

## 1. 论文定位
- 最适合的论文类型：
  - 首选：系统论文 / prototype
  - 次选：工程导向系统论文
  - 不建议：算法论文
- 为什么：
  - 当前最强证据不是新模型、新训练方法或新损失函数，而是一个从 Quest/Unity 前端到 Python Gateway 后端的端到端辅助视觉原型。
  - repo 中最扎实的部分是系统主链、异步调度、安全降级、可观测性、录制回放与评测工具链，而不是算法创新本身。
  - OCR、检测/查找、风险、深度、分割、SLAM pose、HUD、TTS/haptic、recording/reporting 都有代码证据，但不少能力仍是“已接入”而非“已被系统性验证”。
- 当前最稳妥的投稿叙事：
  - 把本文写成“一个面向视障辅助场景的 Quest-to-Gateway 端到端系统原型”，核心在于把采集、感知、反馈、调度和评测组织成同一套可审计运行时。
  - 正文可重点写：Quest 主链、Gateway 聚合、mode-aware 异步调度、本地 fallback、provider truth/capability、run-package 工具链。
  - limitation / ongoing work 可写：planner/VLM 主链化、POV/context 驱动的主动感知、costmap 用户闭环、SLAM 用户闭环、低延迟收益量化。
  - 还不能写：SOTA、用户收益、已验证实时性、成熟主动感知、成熟手眼协调、完整 VLM/VLA 控制闭环。

## 2. 候选标题（给 5 个）
- 偏系统 1：`Be Your Eyes: A Quest-to-Gateway Assistive Vision Prototype with Auditable Runtime Feedback`
- 偏系统 2：`Be Your Eyes: An End-to-End Assistive Vision System Prototype with Mode-Aware Scheduling and Safety Fallbacks`
- 偏系统 3：`Be Your Eyes: A Run-Package-Centric Assistive Perception Prototype for Mixed Reality`
- 偏方法 1：`Mode-Aware Asynchronous Perception and Safety Co-Design for Assistive Mixed Reality`
- 偏 assistive AI / egocentric vision 1：`Be Your Eyes: An Assistive Egocentric Vision Prototype for Quest-Based Perception and Feedback`

## 3. 一句话论文主张
- 保守版：
  - 我们实现了一个 Quest-to-Gateway 的辅助视觉系统原型，将头戴端图像采集、后端多模块感知以及视觉/语音/触觉反馈组织到同一运行时闭环中。
- 平衡版：
  - 我们提出一个面向视障辅助场景的 Quest-based 端到端系统原型，通过 mode-aware 异步调度、本地安全降级和多 provider 集成，把感知、反馈与记录评测统一在同一框架中。
- 更有冲击力但仍诚实版：
  - 我们展示了一个可审计的头戴式辅助视觉系统原型，其核心贡献不在单一模型，而在于把多模块感知、低延迟运行时、安全交互和 run-package 评测工具链组织成同一套端到端系统。

## 4. 摘要素材池
- 背景句：
  - 头戴式辅助视觉系统不仅需要感知能力，还需要稳定的运行时组织、可控反馈和可回查的系统行为。
  - 对视障辅助场景而言，系统价值往往取决于采集、推理、反馈和降级能否在同一闭环内协同工作，而不只是单个模型精度。
- 问题句：
  - 当前 repo 对应的实际工程问题是：如何把 Quest 端视觉采集、后端多模块推理和多模态反馈组织成一个可运行、可审计、可回放的辅助系统原型。
  - 难点不只在模型调用本身，还在于模式切换、异步调度、事件时效、安全降级以及混合真实/外部/mock provider 的状态管理。
- 方法句：
  - 我们采用 Quest-to-Gateway 的系统组织方式，把帧采集、任务触发、后端调度、事件汇总和反馈渲染统一到同一事件链。
  - 后端通过 mode-aware 调度、FAST/SLOW 双层队列、TTL、preempt、provider truth-state 和 fallback 机制管理多能力协同。
- 系统句：
  - 前端由 `Quest3SmokeScene`、`ByesQuest3ConnectionPanelMinimal`、`ScanController`、`GatewayClient`、`ByesVisionHudRenderer`、`ByesHandMenuController` 等组成，负责采集、上传、事件接收与用户反馈。
  - 后端由 `Gateway/main.py` 统一暴露 `/api/frame`、`/ws/events`、`/api/assist`、`/api/plan`、`/api/record/*`、`/api/assets/{asset_id}`、`/api/asr` 等接口，并接入独立 inference/planner/SLAM 服务。
- 关键设计句：
  - 本工作的关键设计不是提出单一新模型，而是在运行时显式组织模式感知调度、事件 TTL/reorder guard、本地 `LocalSafetyFallback`、`LocalActionPlanGate` 和 provider capability/truth-state。
  - 系统还把 run-package 作为统一观测载体，以连接在线运行、离线报告、回放、benchmark 与回归测试。
- 实现句：
  - 当前代码已明确接入 OCR、检测/查找、风险、深度、分割、SLAM pose、target tracking、HUD overlay、TTS/haptic、录制与报告路径。
  - 规划、POV/context、costmap 和 VLM 相关路径也有实现，但其中部分尚未成为 Quest smoke 主场景的默认用户主链。
- 结果句：
  - [待补结果] 当前 repo 已具备 benchmark、latency instrumentation、TUM SLAM 评测、报告生成与回归脚本，但审计阶段未提取出可直接写入摘要的正式定量结果。
  - [待补结果] 若用于投稿，摘要中的性能、延迟、鲁棒性与用户收益表述必须以补充实验为前提。
- 意义句：
  - 本文最适合作为一个可审计的 assistive AI 系统原型来写，其价值在于系统级组织能力而非单模型宣称。
  - 该 repo 已经为论文提供了可落地的系统主线、可追溯的代码证据和可扩展的实验接口。

## 5. 引言素材池
### 5.1 研究问题
- 如何把 Quest 端的视觉采集、模式交互、后端多能力感知、HUD/语音/触觉反馈与记录回放工具链组织成一个真正可运行的辅助视觉原型，而不是若干彼此分离的脚本与服务。
- 如何在系统层同时处理异步性、模式切换、能力退化、事件过期和安全降级。

### 5.2 为什么难
- 代码现实显示，系统横跨 Unity/Quest、Gateway、独立服务和 WebSocket/HTTP 通信层，运行边界多，状态来源复杂。
- repo 中既有本地 provider，也有 HTTP wrapper、mock、reference 和 fallback 路径；系统必须显式表达“能力是否真实可用”，而不能默认每个模块都处于理想状态。
- 对辅助场景而言，错误不仅是感知误差，还包括延迟、旧事件、链路中断、provider 不可用以及不安全反馈。

### 5.3 现有方法缺什么
- 如果论文叙事只围绕单个 detector、OCR 模块或 VLM 接口，就无法解释一个辅助系统如何在真实运行时稳定协同。
- 当前 repo 最能支撑的差异点不是单一模型，而是 runtime orchestration：谁先跑、谁可降级、哪些结果可以丢弃、何时进入 safe mode、如何记录并回放系统行为。

### 5.4 我们的核心思想
- 把系统拆成四层：Quest 端采集与交互、Gateway 端统一编排、可替换 provider/外部服务层、run-package 驱动的观测与评测层。
- 把“低延迟”和“安全”视为运行时协同问题，而不是离线模型问题，通过 FAST/SLOW 队列、TTL、preempt、事件过滤和本地 fallback 共同处理。

### 5.5 我们做了什么
- 实现了一个可运行的 Quest smoke 主链，覆盖扫描、模式切换、read/find、HUD、语音与触觉反馈。
- 实现了一个统一 Gateway 聚合层，暴露 frame ingest、assist、plan、record、asset、ws 事件、confirm、asr 等接口。
- 实现了多 provider 感知接入、target tracking、recording、run-package 报告、benchmark 与 regression 工具链。

### 5.6 当前代码真正支撑的贡献
- 端到端原型：从 Quest 帧采集到 Gateway 推理，再到事件回传、overlay 拉取和用户侧反馈，主链明确存在。
- 运行时设计：mode-aware 调度、FAST/SLOW 双队列、TTL、preempt、LocalSafetyFallback、LocalActionPlanGate、EventGuard 均有真实实现。
- 可观测性：run-package 录制、回放、报告、benchmark、回归脚本和 CI 支撑的是“系统级可复查”，不是一次性 demo。
- 能力接入：OCR、风险、深度、分割、SLAM pose、target tracking 等已接入，但其“主链使用程度”并不完全相同。

### 5.7 本文边界与诚实口径
- 已经能写进论文正文的内容：
  - Quest-to-Gateway 系统原型。
  - Gateway 统一聚合与多接口暴露。
  - mode-aware 异步调度与本地安全降级。
  - run-package 为中心的观测、报告与回归工作流。
- 只能写进 limitation / ongoing work 的内容：
  - planner/VLM 在 Quest 主链中的默认化。
  - POV/context 驱动的主动感知。
  - costmap 的用户端闭环。
  - SLAM 的用户端闭环。
  - 端边云切分收益与低延迟收益的量化验证。
- 还不能写的内容：
  - 用户研究结论。
  - SOTA 或性能领先结论。
  - 已验证实时性。
  - 成熟主动感知、成熟手眼协调、成熟 VLM/VLA 控制闭环。

## 6. 贡献点写法（最关键）
### 套路 A：系统导向
1. 我们实现了一个 Quest-to-Gateway 的端到端辅助视觉系统原型，把头戴端采集、后端感知、HUD/语音/触觉反馈与用户侧 ack 纳入同一运行时闭环。  
`证据强度: High`  
`是否建议写入摘要: Yes`  
`是否建议写入 contribution list: Yes`

2. 我们设计并实现了一个 mode-aware 的异步运行时，包括 FAST/SLOW 调度、TTL、preempt window、事件过滤和本地 fallback。  
`证据强度: High`  
`是否建议写入摘要: Yes`  
`是否建议写入 contribution list: Yes`

3. 我们将多 provider 感知能力与 capability/truth-state 暴露统一到同一 Gateway 框架中，使真实、mock、reference、fallback 与外部服务状态可显式观测。  
`证据强度: High`  
`是否建议写入摘要: Yes`  
`是否建议写入 contribution list: Yes`

4. 我们构建了 run-package 驱动的记录、回放、报告、benchmark 与回归工作流，用于支撑系统级分析而非一次性演示。  
`证据强度: High`  
`是否建议写入摘要: Yes`  
`是否建议写入 contribution list: Yes`

5. 我们在当前主链中接入了 OCR、检测/查找、风险、深度、分割、SLAM pose、target tracking 与多模态反馈等可组合能力。  
`证据强度: Medium`  
`是否建议写入摘要: Yes`  
`是否建议写入 contribution list: Yes`

### 套路 B：方法 + 系统协同导向
1. 我们提出一种面向辅助视觉原型的 mode-aware runtime co-design，把感知触发、事件时效控制与安全反馈统一纳入系统路径。  
`证据强度: High`  
`是否建议写入摘要: Yes`  
`是否建议写入 contribution list: Yes`

2. 我们实现了 prompt-conditioned detection/find 与 target tracking 的统一接入路径，使“扫描-查找-跟踪-反馈”能够在同一事件链中运行。  
`证据强度: Medium`  
`是否建议写入摘要: Yes`  
`是否建议写入 contribution list: Yes`

3. 我们实现了基于 context pack 的 planning 接口，并用 guardrail 与 fallback 机制约束计划输出的安全边界。  
`证据强度: Medium`  
`是否建议写入摘要: No`  
`是否建议写入 contribution list: Yes`

4. 我们把 seg、depth、slam、costmap、POV 等上下文统一组织到后端分析路径中，为系统级规划与离线评测预留统一接口。  
`证据强度: Medium`  
`是否建议写入摘要: No`  
`是否建议写入 contribution list: Yes`

5. 我们提供了可审计的实验接口层，使 latency、OCR、seg、depth、slam 与 costmap 等指标可以在同一 run-package 框架内生成。  
`证据强度: High`  
`是否建议写入摘要: Yes`  
`是否建议写入 contribution list: Yes`

## 7. 论文结构映射
### 1 Introduction
- 这一节应该写什么：
  - 说明头戴式辅助视觉系统的问题不是单模型调用，而是系统化运行时组织。
  - 引出本文聚焦于“可运行原型 + 可审计运行时 + 可回放评测”。
- 可以用 repo 中哪些证据来写：
  - `Assets/Scenes/Quest3SmokeScene.unity`
  - `Assets/BeYourEyes/Unity/Interaction/ScanController.cs`
  - `Assets/BeYourEyes/Adapters/Networking/GatewayClient.cs`
  - `Gateway/main.py`
  - `Gateway/byes/scheduler.py`
  - `Gateway/byes/recording/manager.py`
- 哪些地方缺内容：
  - [待补实验] 缺正式结果支撑“为什么这种系统组织更好”。
  - [待补证据] 缺用户任务层面的实证收益。

### 2 Related Work
- 这一节应该写什么：
  - 对比 assistive AI、egocentric vision、MR assistive interfaces、机器人/代理式 runtime orchestration、端边云协同系统。
  - 重点强调本文贡献不在新感知模型，而在运行时组织和系统可审计性。
- 可以用 repo 中哪些证据来写：
  - 来自审计中已确认的系统特征：Quest 前端、Gateway 聚合、多 provider、run-package、planner/POV/costmap 接口。
- 哪些地方缺内容：
  - [待补证据] related work 需要作者补外部文献，不属于 repo 证据。

### 3 System Overview
- 这一节应该写什么：
  - 概括前端、后端、通信层、provider 层、run-package 工具链的整体分工。
  - 交代 Quest smoke 主链是当前最稳的用户路径。
- 可以用 repo 中哪些证据来写：
  - `Quest3SmokeScene.unity`
  - `ByesQuest3ConnectionPanelMinimal.cs`
  - `ScanController.cs`
  - `GatewayClient.cs`
  - `Gateway/main.py`
  - `Gateway/services/*`
- 哪些地方缺内容：
  - [待补证据] 若要写固定部署拓扑，需要补当前真实部署方式与配置快照。

### 4 Method / Architecture
- 这一节应该写什么：
  - 把本文的方法写成“系统架构方法”，即 mode-aware runtime、模块触发策略、事件表示、provider 封装、context pack 组织。
  - 明确本文不是提出新 detector/OCR/SLAM 算法。
- 可以用 repo 中哪些证据来写：
  - `Gateway/byes/scheduler.py`
  - `Gateway/byes/safety_kernel.py`
  - `Gateway/byes/plan_pipeline.py`
  - `Gateway/services/inference_service/providers/__init__.py`
  - `Gateway/byes/mapping/costmap_fuser.py`
- 哪些地方缺内容：
  - [待补实验] 缺 ablation 结果支撑“该架构设计优于其他设计”。

### 5 Low-Latency Co-Design
- 这一节应该写什么：
  - 聚焦 FAST/SLOW 双层、TTL、取消旧帧、preempt、EventGuard、本地 fallback、asset/frame cache。
  - 强调“low-latency-oriented design”而非“已证明最低延迟”。
- 可以用 repo 中哪些证据来写：
  - `Gateway/byes/scheduler.py`
  - `Assets/BeYourEyes/Adapters/Networking/EventGuard.cs`
  - `Assets/BeYourEyes/Adapters/Networking/LocalActionPlanGate.cs`
  - `Assets/BeYourEyes/Unity/Interaction/LocalSafetyFallback.cs`
  - `Gateway/byes/frame_cache.py`
  - `Gateway/byes/asset_cache.py`
- 哪些地方缺内容：
  - [待补结果] 缺 P50/P90/P99、分模块延迟、不同 provider 配置对比。

### 6 Implementation
- 这一节应该写什么：
  - 交代 Quest/Unity 客户端、Python Gateway、独立 inference/planner/pySLAM 服务、recording/reporting/benchmark 脚本如何组成完整实现。
  - 说明系统具备 provider 切换、truth-state 暴露、测试夹具与历史 run-package 工件。
- 可以用 repo 中哪些证据来写：
  - `Gateway/main.py`
  - `Gateway/services/inference_service/app.py`
  - `Gateway/services/planner_service/app.py`
  - `Gateway/services/pyslam_service/app.py`
  - `Gateway/scripts/report_run.py`
  - `Gateway/scripts/run_regression_suite.py`
  - `Gateway/scripts/run_dataset_benchmark.py`
- 哪些地方缺内容：
  - [待补证据] 缺统一的“论文实验配置表”，需要锁定 provider 版本与开关。

### 7 Experiments
- 这一节应该写什么：
  - 只写 repo 已经具备实验接口的部分：latency、OCR、seg、depth、slam、costmap、planner context、回归验证。
  - 结果必须等补实验后填写。
- 可以用 repo 中哪些证据来写：
  - `Gateway/scripts/bench_risk_latency.py`
  - `Gateway/scripts/eval_slam_tum.py`
  - `Gateway/scripts/ablate_planner.py`
  - `Gateway/scripts/sweep_plan_context_pack.py`
  - `Gateway/scripts/run_dataset_benchmark.py`
  - `Gateway/tests/fixtures/`
- 哪些地方缺内容：
  - [待补结果] 当前没有可直接入文的正式结果表。
  - [待补实验] 缺 Quest 实机端到端稳定性和用户任务评估。

### 8 Discussion / Limitation / Ethics
- 这一节应该写什么：
  - 诚实写出 planner/VLM 主链不明确、主动感知未闭环、手眼协调未落地、SLAM 仍偏 pose/service/eval hook。
  - 讨论辅助场景中的安全、旧事件过滤、本地 safe mode、confirm/ack 路径与 API key 保护。
- 可以用 repo 中哪些证据来写：
  - `LocalSafetyFallback.cs`
  - `LocalActionPlanGate.cs`
  - `Gateway/byes/safety_kernel.py`
  - `Gateway/main.py` 的 `/api/confirm/*`、API key guard
- 哪些地方缺内容：
  - [待补实验] 缺真实用户研究与伦理评估结果。

### 9 Conclusion
- 这一节应该写什么：
  - 收束到“系统原型已打通主链，运行时设计与评测基础设施已经成形”。
  - 不要扩写成“所有设想模块都已成熟完成”。
- 可以用 repo 中哪些证据来写：
  - 端到端主链、run-package、scheduler、safety、provider 封装。
- 哪些地方缺内容：
  - [待补结果] 结论中的性能陈述必须等实验补齐后再写。

## 8. 方法部分素材
### 8.1 Problem Formulation
- 核心论点：
  - 把问题定义为：给定 Quest 端的一帧或一次用户请求，系统需要在有限时效内产生结构化感知结果与多模态反馈，并在链路不稳定时维持安全降级。
- 代码证据：
  - `ScanController.cs`
  - `GatewayClient.cs`
  - `Gateway/main.py` 的 `/api/frame`、`/ws/events`
  - `LocalSafetyFallback.cs`
- 推荐写法：
  - 把输入写成“ego-view frame + mode + target/prompt + source truth + runtime context”，把输出写成“event + overlay asset + speech/haptic + ack/record”。
  - 这是系统问题表述，不必伪装成新数学优化问题。
- 不能过度宣称的点：
  - 不能把问题写成“我们解决了通用 assistive navigation”。
  - 不能写成“本文形式化解决主动感知与规划闭环”，因为当前证据不足。

### 8.2 System Overview
- 核心论点：
  - 系统由 Quest 前端、Gateway 聚合层、可替换 provider/独立服务层、run-package 工具链四部分组成。
- 代码证据：
  - `Assets/Scenes/Quest3SmokeScene.unity`
  - `ByesQuest3ConnectionPanelMinimal.cs`
  - `ScanController.cs`
  - `GatewayClient.cs`
  - `Gateway/main.py`
  - `Gateway/services/inference_service/app.py`
  - `Gateway/services/planner_service/app.py`
- 推荐写法：
  - 用一张总览图把“采集-上传-推理-事件-反馈-记录”主链画清楚。
  - 强调 `Gateway/main.py` 是统一后端入口，而不是多个松散脚本并列。
- 不能过度宣称的点：
  - 不能把“多服务存在”直接写成“已经验证的端边云最优切分”。

### 8.3 Module Instantiation
- 核心论点：
  - 论文中的模块实例化可以围绕 OCR、检测/查找、风险、深度、分割、SLAM pose、target tracking、HUD/TTS/haptic 来写。
- 代码证据：
  - OCR：`Gateway/main.py` OCR 路径，`Gateway/services/inference_service/providers/paddleocr_ocr.py`
  - 检测/查找：`Gateway/main.py` assist/open-vocab 路径，`ultralytics_det.py`
  - 风险：`Gateway/byes/safety_kernel.py`
  - 深度：`onnx_depth.py`
  - SLAM：`Gateway/services/pyslam_service/app.py`，`Gateway/scripts/eval_slam_tum.py`
  - target tracking：`Gateway/byes/target_tracking/*`
- 推荐写法：
  - 不要把这些写成“新算法模块”；应写成“系统中被实例化和接入的能力模块”。
  - 可以在小表格里标注哪些进入主链、哪些为 optional/partial。
- 不能过度宣称的点：
  - 不能把 open-vocab 检测写成成熟创新算法。
  - 不能把 SLAM 写成完整在线建图导航闭环。

### 8.4 Edge-Cloud Collaboration
- 核心论点：
  - repo 支持本地 Quest 交互与后端多服务协同，架构上具有端边云协同潜力。
- 代码证据：
  - Quest 本地：`Quest3SmokeScene.unity`、`LocalSafetyFallback.cs`
  - Gateway 聚合：`Gateway/main.py`
  - HTTP 外部服务：`Gateway/services/inference_service/app.py`、`planner_service/app.py`、`pyslam_service/app.py`
  - provider truth-state：`Gateway/services/inference_service/providers/__init__.py`
- 推荐写法：
  - 建议写成“an architecture that supports mixed local/remote execution and explicit capability state”。
  - 强调的是“架构支持存在”，不是“端边云收益已被量化证明”。
- 不能过度宣称的点：
  - 不能写“我们证明了端边云协同显著降低延迟/成本”，因为没有结果。

### 8.5 Low-Latency Pipeline
- 核心论点：
  - 当前系统有明确的低延迟导向设计：FAST/SLOW 双层调度、TTL、取消旧帧、preempt、EventGuard、asset/frame cache、本地 fallback。
- 代码证据：
  - `Gateway/byes/scheduler.py`
  - `Gateway/byes/frame_cache.py`
  - `Gateway/byes/asset_cache.py`
  - `EventGuard.cs`
  - `LocalSafetyFallback.cs`
  - `LocalActionPlanGate.cs`
- 推荐写法：
  - 把这一节写成“co-design of runtime latency and safety”，而非简单罗列优化技巧。
  - 可以明确指出：系统区分快路径风险感知与慢路径复杂分析。
- 不能过度宣称的点：
  - 不能写“实现了实时性能”或“优于现有系统”，除非补齐定量结果。

### 8.6 Safety and Interaction Design
- 核心论点：
  - 系统在客户端和后端都引入了安全相关控制：本地 fallback、事件过滤、action gate、planner safety kernel、confirm/ack 交互。
- 代码证据：
  - `LocalSafetyFallback.cs`
  - `LocalActionPlanGate.cs`
  - `EventGuard.cs`
  - `Gateway/byes/safety_kernel.py`
  - `Gateway/main.py` 的 `/api/confirm/*`、`/api/frame/ack`
  - `ByesHandMenuController.cs`
- 推荐写法：
  - 强调“安全策略是运行时结构的一部分”，而不是训练后附加规则。
  - 可写“系统优先避免旧事件、失连状态和不安全动作建议继续传播到用户侧”。
- 不能过度宣称的点：
  - 不能写“该系统已验证具备临床级或产品级安全性”。

### 8.7 Implementation Details
- 核心论点：
  - 实现层面最值得写的是：Quest smoke 主场景、统一 Gateway、独立 inference/planner/SLAM 服务、recording/reporting/benchmark 脚本，以及丰富的 fixtures/run-packages。
- 代码证据：
  - `Assets/Scenes/Quest3SmokeScene.unity`
  - `Gateway/main.py`
  - `Gateway/services/inference_service/app.py`
  - `Gateway/services/planner_service/app.py`
  - `Gateway/services/pyslam_service/app.py`
  - `Gateway/byes/recording/manager.py`
  - `Gateway/scripts/report_run.py`
  - `Gateway/scripts/run_regression_suite.py`
  - `Gateway/tests/fixtures/`
- 推荐写法：
  - 这一节应突出“系统实现完整度”和“评测接口完备度”。
  - 如果篇幅有限，可把 provider 细节压到 appendix。
- 不能过度宣称的点：
  - 不能把“有脚本/有入口”直接写成“所有模块都已在统一实验设置下完整验证”。

## 9. 实验部分素材
### 9.1 当前已有
- 有推理/服务运行入口：`Gateway/main.py`、`Gateway/services/inference_service/app.py`、`Gateway/services/planner_service/app.py`、`Gateway/services/pyslam_service/app.py`。
- 有 benchmark / report / replay / regression 基础设施：`Gateway/scripts/report_run.py`、`Gateway/scripts/run_regression_suite.py`、`Gateway/scripts/run_dataset_benchmark.py`。
- 有特定评测接口：`Gateway/scripts/eval_slam_tum.py`、`Gateway/scripts/bench_risk_latency.py`、`Gateway/scripts/ablate_planner.py`、`Gateway/scripts/sweep_plan_context_pack.py`。
- 有大量最小夹具和历史 run-package 工件：`Gateway/tests/fixtures/`、`Gateway/artifacts/run_packages/`。
- 目前没有在审计输出中沉淀成论文可直接引用的正式结果表。  
  - `[待补结果]`

### 9.2 目前缺失
- 缺固定 provider 配置快照；否则实验不可复现。
- 缺 Quest 实机端到端结果表。
- 缺 scheduler / fallback / context pack 的正式消融结果。
- 缺用户研究、任务成功率和主观反馈。
- 缺“端边云收益”“低延迟收益”的正式量化对比。  
  - `[待补实验]`

### 9.3 必须补的实验
- P0：固定 provider 和开关后的核心任务结果表。  
  - 内容可覆盖 OCR、find/detection、risk、seg、depth、slam、costmap。  
  - `[待补实验]`
- P0：Quest 端到端延迟与稳定性评估。  
  - 内容应至少包括 frame ingest 到 feedback/ack 的 P50/P90/P99、event drop rate、fallback enter rate。  
  - `[待补实验]`
- P0：关键运行时消融。  
  - 内容应包括 scheduler preempt on/off、EventGuard on/off、LocalSafetyFallback on/off、provider real/mock/fallback。  
  - `[待补实验]`
- P1：planning/context pack 消融。  
  - 内容应包括 POV/seg/slam/costmap context on/off、guardrail on/off、fallbackUsed rate。  
  - `[待补实验]`
- P1：SLAM / costmap 质量评估。  
  - 内容应包括 TUM ATE/RPE、tracking rate、costmap stability。  
  - `[待补实验]`

### 9.4 推荐 benchmark / baseline / metric
- benchmark：
  - OCR、seg、depth、slam、plan、POV、costmap 可优先基于 `Gateway/tests/fixtures/` 与 run-package 路径组织。
  - SLAM 可直接使用 `Gateway/scripts/eval_slam_tum.py` 的 TUM 路径。
- baseline：
  - 不建议杜撰外部 baseline；优先使用 repo 已支持的运行时对比。
  - 推荐 baseline 形式是：不同 provider、不同 runtime 开关、不同 context pack 组合、不同 fallback 策略。  
  - `[待补结果]`
- metric：
  - latency：`riskLatencyP90`、`frame_e2e_p90`、event drop rate、fallbackUsed rate。
  - OCR：CER / WER 或 repo 实际报告字段。  
  - seg：F1 / mask coverage。
  - depth：AbsRel 或 repo 实际报告字段。
  - slam：ATE / RPE / tracking rate。
  - costmap：stability / flicker / shift gate。  
  - `[待补证据] 具体最终字段应以实际报告输出为准`

### 9.5 失败案例与消融建议
- 失败案例建议：
  - prompt-conditioned find 失败或错检。
  - seg mask 漏检或过度覆盖。
  - depth unavailable。
  - SLAM lost / tracking reset。
  - LocalSafetyFallback 进入 `STALE` / `DISCONNECTED` / `SAFE_MODE_REMOTE`。
- 消融建议：
  - runtime 侧：scheduler preempt、TTL、EventGuard、LocalSafetyFallback、LocalActionPlanGate。
  - context 侧：POV、seg、slam、costmap context pack。
  - provider 侧：real/mock/reference/fallback 切换。
- 当前状态：
  - 这些图和表在 repo 中有接口基础，但没有现成论文结果。  
  - `[待补结果]`

## 10. 图表与附录写作素材
- 图 1 画什么：
  - 画系统总览图：Quest 端采集与交互、Gateway 聚合、独立服务、provider 层、run-package/report 工具链。
  - 可直接取材于：`Quest3SmokeScene.unity`、`ScanController.cs`、`GatewayClient.cs`、`Gateway/main.py`、`Gateway/services/*`、`Gateway/byes/recording/manager.py`。
- 图 2 画什么：
  - 画一帧的时序与低延迟流水线：scan/read/find 触发、帧上传、scheduler FAST/SLOW、事件发射、HUD overlay、speech/haptic、ack、record。
  - 可直接取材于：`ScanController.cs`、`Gateway/main.py`、`Gateway/byes/scheduler.py`、`EventGuard.cs`、`LocalSafetyFallback.cs`、`ByesVisionHudRenderer.cs`、`SpeechOrchestrator.cs`。
- 表 1 放什么：
  - 放模块状态表：OCR、find/det、risk、depth、seg、slam、costmap、planner、POV、hand input、HUD、recording。
  - 建议列：是否实现、是否进入 Quest 主链、是本地模型/外部服务/传统算法/接口包装、论文可否写入正文。
- 表 2 放什么：
  - 放实验设计表，而不是先放结果表。
  - 建议列：实验目的、对应脚本、输入来源、输出指标、当前状态。  
  - 当前结果栏统一可写 `[待补结果]`。
- Appendix 可以放什么：
  - provider 配置快照与 truth/capability 说明。
  - Quest smoke 主链涉及的场景和脚本清单。
  - run-package schema 与关键字段。
  - planner/context pack 字段定义。
  - 失败案例扩展图、fallback 触发日志、接口 contract 示例。

## 11. 最终 claim 边界
- 哪些句子现在绝对不能写：
  - “我们的方法在辅助视觉任务上达到 SOTA。”
  - “系统已通过真实视障用户研究验证有效。”
  - “系统已经证明具备实时性能。”
  - “系统已实现完整 3D 建图 / SLAM 导航闭环。”
  - “系统已实现在线主动感知 / 视角规划闭环。”
  - “系统已具备手眼协调能力。”
  - “VLM/VLA 是当前 Quest 主工作流的核心控制器。”
- 哪些句子可以保守写：
  - “The repository supports a mixed local/remote architecture with explicit capability state.”
  - “The prototype includes mode-aware asynchronous scheduling and runtime safety fallbacks.”
  - “Planning, POV/context, costmap, and SLAM-related paths are partially implemented and can be discussed as ongoing work.”
  - “The system exposes hooks for latency, SLAM, and context-related evaluation.”  
  - 上述句子若入正文，应避免配过强结果性措辞。
- 哪些句子可以自信写：
  - “The repository contains a Quest-to-Gateway end-to-end assistive vision prototype.”
  - “`Gateway/main.py` serves as a unified backend entry for frame ingest, assist, planning, recording, assets, and WebSocket events.”
  - “The current system includes explicit runtime safety mechanisms, including local fallback, event filtering, and planner-side guardrails.”
  - “The repository includes a run-package-based recording, replay, reporting, benchmarking, and regression workflow.”
  - “OCR、risk、depth、seg、SLAM pose、target tracking 等能力在 repo 中具有明确接入证据，但其主链成熟度并不完全相同。”

## 12. 交给作者写初稿时最有用的简版提纲
- 这篇论文不要写成算法论文，要写成“面向视障辅助场景的 Quest-to-Gateway 系统原型”。第一段先讲问题：辅助视觉真正困难的是采集、推理、反馈、安全和降级的系统协同，而不只是单模型。第二段写本文核心：我们把 Quest 端采集、Gateway 编排、多 provider 感知、HUD/语音/触觉反馈和 run-package 评测组织成同一运行时。第三段给主贡献，优先写端到端主链、mode-aware 异步调度、LocalSafetyFallback/EventGuard/ActionPlanGate、安全 guardrail、run-package 工具链。方法部分先写系统总览，再写模块实例化，再写低延迟与安全协同设计，最后写实现。实验部分现在只能先写“实验设计与接口”，结果位全部留成 `[待补结果]`；至少要预留 latency、核心任务表、scheduler/fallback 消融、SLAM/TUM、失败案例。discussion 必须主动承认：planner/VLM 尚未明确成为 Quest 主链默认路径，主动感知、手眼协调、costmap 用户闭环、SLAM 用户闭环都只能写 ongoing work，不能写成已完成贡献。
