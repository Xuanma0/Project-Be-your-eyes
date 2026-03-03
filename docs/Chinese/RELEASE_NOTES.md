Current development version is defined by `VERSION`; this file records historical milestones only.

## v5.05
- Added Quest real-frame source abstraction (IByesFrameSource) with PCA capture scaffolding (ByesPcaFrameSource) and render-texture fallback; frame-source metadata is now attached in /api/frame upload meta.
- Added Desktop Console (GET /ui, GET /api/ui/state) to show provider real/mock evidence, latest frame/overlay preview, and quick actions (ping/mode/assist/record).
- Extended Gateway overlay bus with vis.overlay.v1 companion events for DET/SEG/DEPTH assets and latest overlay index for Quest HUD + desktop preview.
- Extended Quest smoke panel observability with provider summary (real/mock/off) and capture source/resolution stats, with low-frequency capabilities refresh.
- Added one-command launcher tools/quest3/quest3_usb_realstack_v5_05.cmd (USB reverse + gateway/inference + optional pySLAM bridge + auto-open desktop console).

## v5.04
- 新增 Quest 视觉 HUD 资产闭环：支持 `det.objects.v1` 框/标签/trackId、`seg.mask.v1` 蒙版资产、`depth.map.v1` 深度资产叠加显示。
- Gateway 新增资产接口：`GET /api/assets/{asset_id}` 与 `GET /api/assets/{asset_id}/meta`，避免在 WS 事件中传大体积 base64。
- 新增可选语音输入入口 `POST /api/asr`：默认 `mock` 后端，支持可选 `faster-whisper`，并发出 `asr.transcript.v1`。
- 录制链路增强：Quest recording 在生成 run package 时同步落盘引用的 `assets/` 文件，保持 replay/report 兼容。
- 新增 v5.04 一键 USB realstack 脚本 `tools/quest3/quest3_usb_realstack_v5_04.cmd`（gateway + inference + 可选 pySLAM 检测）与配套验收指引。
- Quest 手腕菜单信息架构收敛为 `Home / Vision / Guidance / Voice / Dev`，支持“Pin Last Action 到 Home”收藏动作，并保留显式 Move/Resize 保护。
- 新增透视扩展控制（开关、透明度、彩色/灰度可选）与 v5.04 自检扩展（HUD 资产、TTS/ASR、可选 pySLAM realtime 状态）。

## v5.03
- 新增 Target Tracking Assist：`POST /api/assist` 支持 `target_start / target_step / target_stop`，并发出 `target.session` / `target.update` 事件。
- Quest 面板新增 `Last TARGET`（含 Age），并接入 Guidance 文本 + 空间音频/触觉开关。
- 新增可选 Passthrough 控制桥接（`ByesPassthroughController`）与菜单开关状态显示。
- 新增可选 pySLAM 离线脚本 `Gateway/scripts/pyslam_run_package.py` 与 `services/pyslam_service` 桥接骨架。
- 新增一键 USB realstack 脚本：`tools/quest3/quest3_usb_realstack_v5_03.cmd`。

## v5.02
- Promptable Find：在 real DET 基础上增加概念查找（Find Door / Exit Sign / Stairs / Elevator / Restroom / Person）。
- Gateway 新增 `POST /api/assist`：复用最近帧缓存执行 `ocr/det/find/risk/depth/seg`，Quest 无需重复上传帧。
- Gateway 新增录制链路：`POST /api/record/start` 与 `POST /api/record/stop`，生成可回放 run package（含 `frames_meta.jsonl` 与 `events/events_v1.jsonl`）。
- Quest 面板新增 `Last FIND` 与 `Guidance`（含 Age），并支持 `Auto Speak FIND / Auto Guidance`（去重与冷却保护）。
- 新增一键脚本 `tools/quest3/quest3_usb_realstack_v5_02.cmd`：USB reverse + gateway + inference + 能力检查提示。

## v5.01
- inference_service 新增真实 OCR provider（PaddleOCR）：`BYES_SERVICE_OCR_PROVIDER=paddleocr`，缺依赖时返回明确 `503` 提示。
- inference_service 新增真实 DET provider（Ultralytics YOLO）：`BYES_SERVICE_DET_PROVIDER=ultralytics`，统一输出 `det.objects` 事件。
- Gateway `/api/frame` 增强：支持 `meta.targets` 强制单次目标（OCR/DET/DEPTH/RISK 等），并新增 `GET /api/capabilities` 供 Quest 面板与自检读取能力状态。
- 新增深度融合风险事件 `risk.fused`（基于 depth grid 的左右/中间最小距离与建议方向）。
- Quest 面板新增可用输出：`Last OCR/DET/RISK + Age(ms)`；增加 `Read Text Once / Detect Once`；支持 `AutoSpeak OCR/DET/RISK` 与 `OCR Verbose`（带去重+冷却保护）。
- 新增一键脚本 `tools/quest3/quest3_usb_realstack_v5_01.cmd`：USB reverse + 启动 gateway/inference + 依赖缺失提示。

## v5.00
- Quest 主入口交互切换为官方手掌菜单流程（XRI `HandMenu` + `MetaSystemGestureDetector`），替代旧自定义 wrist button 逻辑。
- 手菜单支持多级分组页：`Connection / Actions / Mode / Panels / Settings / Debug`，包含 mode 设置与回读、panel 控制、debug 导出、passthrough 开关。
- 新增 Safe 手势快捷模式：仅在菜单隐藏、无 UI/grab 冲突、无系统手势活跃时触发。
- Smoke Panel 新增显式 Move/Resize 开关（默认关）、LockToHead、Reset Pose/Scale，减少 pinch 误拖动。
- Quest3SmokeScene 新增 MR Template Guide/Coaching 运行时禁用器，默认隐藏干扰组件。
- 场景安装器更新：自动配置 `BYES_HandMenuRoot` + `ByesMrTemplateGuideDisabler`，并默认将 Build Settings 收敛为 `Quest3SmokeScene`。

## v4.99
- Quest3 烟测交互升级为手腕/手掌菜单（`Actions / Panels / Debug`），默认不再依赖底部蓝色按钮。
- 新增 XR Hands 手势快捷：右手拇指+食指=`Scan Once`，拇指+中指=`Live Toggle`，拇指+无名指=`Cycle Mode`。
- 连接面板支持抓取拖拽、Pin/Unpin、距离与缩放调节、`Snap Default` 复位。
- Quest3 场景安装器自动注入腕部菜单与手势组件，并默认关闭 Coaching/Tutorial UI。
- 新增编辑器自动打开 `Quest3SmokeScene` 开关，并同步更新 Quest3 runbook。

## v4.98
- Quest3 卡顿缓解：采集链路支持 Async GPU Readback（Android 默认启用），不支持时自动回退同步路径。
- 新增头显内卡顿观测指标：`Hitch30s`、`WorstDt`、`AvgDt`、`GC delta`，并在面板显示采集状态（CaptureHz / inflight / async）。
- Quest 面板模式按钮可真正切换模式：`Walk / Read / Inspect`，通过 `POST /api/mode` 写入并 `GET /api/mode` 回读验证。
- 烟测轮询节流：自动探测降低频率，提供显式 `Refresh` 按钮进行手动刷新。
## v4.97
- Quest3 最小连接面板新增 `Scan Once` 与 `Live Start/Stop`，并展示 `HTTP reachable / WS connected / Last Upload(ms) / Last E2E(ms) / Last Event Type`，支持仅手势点击完成闭环验证。
- Quest3 自检流程更新为 `Ping -> Version -> Mode -> Scan Once + WS event`，并输出明确 `PASS/FAIL` 与失败原因（例如网关不可达、无 WS 回包）。
- Quest3 场景安装器升级：自动在 `Quest3SmokeScene` 注入 `BYES_FrameRig`，包含 `GatewayClient + ScreenFrameGrabber + FrameCapture + GatewayFrameUploader + ScanController`，默认参数针对烟测带宽与背压。
- USB 一键脚本默认开启 `BYES_INFERENCE_EMIT_WS_V1=1` 与 `BYES_EMIT_NET_DEBUG=1`，提高 Scan 后 WS 回包可观测性。
## v4.96.1
- Quest3 UI 可点击修复：MODE Overlay 在 Android 下默认禁用，并且非 Android 下关闭射线拦截，避免遮挡交互。
- 强化 Quest 连接面板运行时配置：固定 WorldSpace + 主相机绑定 + 高 sortingOrder + 优先 TrackedDeviceGraphicRaycaster + 面板可交互。
- 新增运行时守护 ByesXrUiWiringGuard：统一 EventSystem 使用 XRUIInputModule，并自动开启 XRRayInteractor 的 UI 交互开关。
- 更新 Quest3 场景安装器：自动在 BYES_SmokeRig 下安装 BYES_XrUiWiringGuard。

## v4.96
- 新增 Quest3 Smoke 场景自动安装器，确保 `Quest3SmokeScene` 内自动存在 `BYES_SmokeRig/BYES_ConnectionPanel`。
- 新增头锁定世界空间面板脚本 `ByesHeadLockedPanel`，面板自动跟随到用户前方并朝向用户。
- 新增无 Prefab 依赖的最小连接面板 `ByesQuest3ConnectionPanelMinimal`，支持 `Ping / Version / Mode` 与周期性 HTTP 可达性探测。
- 新增批处理入口 `BYES.Editor.ByesQuest3SmokeSceneInstaller.InstallFromBatch`，无需手动点菜单即可安装。
- 更新 Quest3 运行手册，补充“只看到 MODE 文字但没有面板”排查步骤。

## v4.95
- 新增 Quest3 Android 批处理构建入口：BYES.Editor.ByesBuildQuest3.BuildQuest3SmokeApk，产物输出到 Builds/Quest3/。
- 新增本地一键 Android 构建脚本：tools/unity/build_quest3_android.cmd，并补充 tools/unity/README_BUILD_ANDROID.md。
- 新增 Unity 构建日志根因提取脚本：tools/unity/parse_unity_build_log.py，可定位首个真实报错并输出上下文摘要。
- 新增 Quest3 USB 本机网关脚本：tools/quest3/quest3_usb_local_gateway.cmd（adb reverse + 本机 18000 端口）。
- 更新 Quest3 runbook：补充 USB 推荐路径、WinError 10013 端口规避、以及可拍照核验清单。

## v4.94
- Quest3 新增“零控制器自检”闭环：启动后自动执行 ping/version/mode/live-loop，并在连接面板显示 RUNNING/PASS/FAIL 与关键指标。
- 输入系统迁移加固：BYES 运行时脚本去除未加条件编译的 Input.GetKey* 调用，旧输入仅允许在 #if ENABLE_LEGACY_INPUT_MANAGER 内使用。
- Quest3 运行时新增 XR 子系统护栏：当不存在可用 XRHandSubsystem 时自动禁用 XRInputModalityManager，避免 HandTracking spam。
- 新增 Windows 一键脚本 tools/quest3/quest3_smoke.ps1，支持 USB/LAN 启动 Gateway 并可自动执行 adb reverse。
- 新增 CI 防回归脚本 tools/check_unity_legacy_input.py，阻止旧输入 API 无条件回流。

## v4.93
- 修复 Unity 编译失败：移除 Assets/BeYourEyes/** 对 BYES 命名空间的编译期依赖。
- 增加分层安全运行时桥接（GatewayRuntimeContext + BYES 侧注册），保持功能语义同时解耦 assembly 边界。
- 新增仓库防回归脚本 tools/check_unity_layering.py，并接入 CI，阻止 Assets/BeYourEyes/** 再次引入 using BYES...。
- Quest3 构建链路继续可用（连接面板 Ping/Version/Mode + Live Loop smoke）。
## v4.92
- Quest 3: added Live Loop controls (toggle/FPS/max in-flight/backpressure) in Unity scan flow.
- Quest 3: added default downscale + JPEG quality controls for bandwidth stability.
- Gateway: added GET /api/version (version/gitSha/uptime/profile) for runtime diagnostics.
- Runtime panel: shows HTTP/WS status, ping RTT, last upload cost, coarse E2E, and version probe button.
- Added tests/docs updates for v4.92 (/api/version, Quest runbook, config matrix, API inventory).

## v4.91
- 鏂板 Quest 3 鐑熸祴闂幆鏀寔锛?  - 杩愯鏃惰繛鎺ラ潰鏉匡紙涓绘満/IP銆佺鍙ｃ€丄PI Key銆侀噸杩烇級
  - 鍙虫墜鎺у埗鍣ㄦ寜閽Е鍙戞壂鎻忎笂浼狅紙淇濈暀妗岄潰 `S` 浣滀负鍥為€€锛?  - 鏂板 `Quest3SmokeScene` 骞跺姞鍏?Build Settings锛屽鍔犺繍琛屾椂 passthrough 閰嶇疆杈呭姪鑴氭湰
- 鏂板 Gateway 杩愯鎬佹煡璇㈢鐐癸細
  - `GET /api/mode`锛堢洿鎺ヨ鍙?mode state store锛?  - `POST /api/ping`锛堣交閲?RTT 鎺㈡祴锛?- 鏂板/鏇存柊瀵瑰簲娴嬭瘯锛堝惈 API Key 寮€鍚椂鐨勯壌鏉冭涓猴級銆?- 鏇存柊 runbook 涓庨厤缃煩闃碉紝琛ュ厖 Quest 灞€鍩熺綉杩炴帴璇存槑鍜屾柊绔偣/閰嶇疆椤广€?
## v4.90
- 鏂板 mode 绔簯鍚屾璋冨害锛歎nity 妯″紡鍒囨崲閫氳繃 `/api/mode` 鍐欏叆 Gateway 杩愯鎬?mode store锛坄Gateway/byes/mode_state.py`锛夈€?- 鏂板 `BYES_MODE_PROFILE_JSON`锛屾敮鎸佹寜 mode 閰嶇疆鍚勬劅鐭ョ洰鏍囩殑 `every_n_frames`锛堢┖鍊兼椂淇濇寔鏃ц涓猴紝鍚戝悗鍏煎锛夈€?- 鏂板 `BYES_EMIT_MODE_PROFILE_DEBUG`锛屽彲杈撳嚭 `mode.profile` 璋冭瘯浜嬩欢锛屼究浜庢牳楠屾瘡甯цЕ鍙?璺宠繃鐩爣銆?- 鏂板鍗曞厓娴嬭瘯锛歮ode profile 瑙ｆ瀽涓庡洖閫€銆乵ode state TTL/LRU 涓?changed-flag銆乻tride 鍒ゅ畾瑙勫垯銆?
## v4.89
- 鏂板 Gateway 閮ㄧ讲妗ｄ綅锛歚BYES_GATEWAY_PROFILE=local|hardened`锛宍hardened` 涓嬮粯璁ゅ紑鍚祫婧愪笌鏆撮湶闈㈡姢鏍忋€?
- 鏂板璧勬簮鎶ゆ爮锛氳姹備綋澶у皬闄愬埗锛坄BYES_GATEWAY_MAX_*_BYTES`锛変笌閫熺巼闄愬埗锛坄BYES_GATEWAY_RATE_LIMIT_*`锛夈€?
- 鏂板鍏ュ彛鎶ゆ爮锛歚/api/dev/*`銆乣/api/mock_event`銆乣/api/run_package/upload` 涓庢湰鍦拌矾寰勮緭鍏ュ彲閫氳繃鐜鍙橀噺鎸夋。浣嶇鐢ㄣ€?
- 鏂板 CI 妫€鏌ワ細Unity `.meta` 瀹屾暣鎬э紙`tools/check_unity_meta.py`锛変笌鏂囨。鐩稿閾炬帴鏈夋晥鎬э紙`tools/check_docs_links.py`锛夈€?

## v4.88
- Added `Gateway/scripts/dev_up.py` for one-command local orchestration (Gateway + optional inference/planner/reference services).
- Added optional Gateway API key guard for HTTP + WebSocket (`BYES_GATEWAY_API_KEY`) and optional host/origin allowlists.
- Added API key compatibility in Unity clients and `Gateway/scripts/replay_run_package.py` (`X-BYES-API-Key` + WS `api_key` query).

# 鐗堟湰鍙戝竷璁板綍锛坴4.x锛?

鏈枃妗ｆ寜鐗堟湰鎬荤粨 `v4.38` 鍒?`v4.82` 鐨勬牳蹇冭兘鍔涢棴鐜紝渚夸簬璇勫涓庣淮鎶ゃ€?

## v4.38
- 瑙勫垝璇勬祴鎸囨爣銆乤blation 鎵弬锛坄provider/prompt/budget`锛夈€佹帓琛屾/鎶ュ憡鎺ュ叆銆佸洖褰掗棬绂併€?

## v4.39-v4.40
- POV 瑙勫垝閫傞厤鍣紙`pov.ir.v1 -> action_plan.v1`锛夈€?
- 鍦ㄧ嚎 POV ingest API + 鍐呭瓨瀛樺偍 + inline `povIr` 瑙勫垝閾捐矾銆?

## v4.41
- 濂戠害鍐荤粨鏈哄埗锛坄Gateway/contracts/*` + `contract.lock.json`锛夈€?
- `/api/contracts` 涓?suite/CI 涓ユ牸濂戠害鏍￠獙銆?

## v4.42-v4.44
- 鍒嗗壊 provider 閾捐矾锛坄mock/http`锛変笌 `/seg`銆?
- 鍒嗗壊璐ㄩ噺鎸囨爣 + GT fixture銆?
- `byes.seg.v1` 鍐荤粨涓?payload 褰掍竴鍖栨牎楠屻€?

## v4.45-v4.47
- `reference_seg_service` 涓?HTTP E2E銆?
- 鍒嗗壊鎻愮ず濂戠害锛坄byes.seg_request.v1`锛? prompt 閫忎紶 + `seg.prompt` 浜嬩欢銆?

## v4.48-v4.50
- `byes.seg.v1` 鍙€?mask锛坄rle_v1`锛変笌 mask 璐ㄩ噺鎸囨爣銆?
- prompt-conditioned 鍒嗗壊琛屼负涓?prompt+mask 濂戠害瑕嗙洊銆?

## v4.51-v4.52
- 鍒嗗壊鎻愮ず棰勭畻/鎴柇宸ョ▼鍖栥€?
- Seg ContextPack锛坄seg.context.v1`锛? `/api/seg/context` + planner prompt v2 鍙€夋嫾鎺ャ€?

## v4.53-v4.55
- `byes.plan_request.v1` + 涓婁笅鏂囨劅鐭?planner HTTP 璇锋眰銆?
- 鍙В閲?seg-hint 瑙勫垯灞傘€?
- plan-context 瀵归綈鎸囨爣锛坄plan.context_alignment.v1`锛夈€?
- 缁熶竴 PlanContextPack锛坄plan.context_pack.v1`锛? `/api/plan/context`銆?

## v4.56-v4.58
- 鍗曡姹?plan context pack override銆?
- context sweep 宸ュ叿銆?
- 甯х骇 E2E 寤惰繜濂戠害/浜嬩欢锛坄frame.e2e.v1`锛変笌鍞竴鎬?涓€鑷存€у姞鍥恒€?

## v4.59-v4.60
- `frame.input.v1` + `frame.ack.v1` + capture->feedback user-E2E 鎸囨爣銆?
- 鎸?kind锛坄tts/ar/haptic`锛夊垎妗剁殑 user-E2E 鎶ュ憡/鎺掕姒溿€?

## v4.61-v4.64
- 娣卞害鑳藉姏閾捐矾锛坄byes.depth.v1`銆乺eference depth service銆佽川閲忚瘎娴嬶級銆?
- 妯″瀷璧勪骇娓呭崟锛坄byes.models.v1`銆乣/api/models`銆乣verify_models.py`锛夈€?
- OCR 鑳藉姏閾捐矾锛坄byes.ocr.v1`銆乺eference OCR銆丆ER/瀹屽叏鍖归厤鎸囨爣锛夈€?
- SLAM pose 鑳藉姏閾捐矾锛坄byes.slam_pose.v1`銆乺eference SLAM銆佺ǔ瀹氭€ф寚鏍囷級銆?

## v4.65-v4.66
- `sam3_seg_service`锛坒ixture/sam3锛変笌涓嬫父鍒囨崲銆?
- `da3_depth_service`锛坒ixture/da3锛変笌涓嬫父鍒囨崲銆?
- SAM3/DA3 妯″瀷鏂囦欢瑕佹眰绾冲叆妯″瀷娓呭崟鏍￠獙銆?

## v4.67-v4.75
- pySLAM TUM 杞ㄨ抗娉ㄥ叆涓虹绾?`slam.pose` 浜嬩欢銆?
- 鏁版嵁闆嗗鍏ュ櫒锛圗go4D 瑙嗛 / 鍥剧墖鐩綍锛変笌 benchmark 鎵硅窇 + matrix profiles銆?
- pySLAM prehook锛坄pyslam_ingest`銆乣pyslam_run`锛夈€?
- SLAM 杞ㄨ抗璇樊鎸囨爣锛坄ATE/RPE`锛夈€?
- SlamContextPack锛坄slam.context.v1`锛? `/api/slam/context`銆?

## v4.76-v4.79
- 灏?SLAM context 鎺ュ叆 plan_request 涓?planner prompt锛坄v3`锛夈€?
- Local costmap锛坄byes.costmap.v1`锛? costmap context锛坄costmap.context.v1`锛? planner prompt锛坄v4`锛夈€?
- Fused costmap锛坄byes.costmap_fused.v1`锛孍MA/鍙€?shift锛夈€?
- Shift gate锛堝彲瑙ｉ噴 reject 鍘熷洜锛変笌 online/final 杞ㄨ抗 profile 瀵规瘮銆?

## v4.80-v4.81
- SAM3 tracking 閫忎紶锛坄trackId`銆乣trackState`锛変笌 segTracking 鎸囨爣銆?
- 鍩轰簬 trackId 鐨勫姩鎬侀殰纰嶆椂搴忕紦瀛橈紝鎺ュ叆 costmap/costmap_fused銆?

## v4.82
- DA3 `refViewStrategy` 绔埌绔€忎紶銆?
- 娣卞害鏃跺簭涓€鑷存€ф寚鏍囷細
  - `jitterAbs`
  - `flickerRateNear`
  - `scaleDriftProxy`
  - `refViewStrategyDiversityCount`
- 鎺ュ叆 report/leaderboard/linter/contract gate/matrix summary銆?

