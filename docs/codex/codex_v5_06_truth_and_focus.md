# Codex v5.06 Prompt (Truth & Focus)

> Type: Version execution plan
> Purpose: only for `v5.06` execution; not long-term memory.
> Usage: read `docs/maintainer/ARCHITECTURE_REVIEW.md`, `docs/maintainer/CODEX_HANDOFF.md`, `docs/maintainer/REPO_FACTS.json`, and `docs/maintainer/ACTIVE_PLAN.md` first, then read this file.

> Use this prompt after reading:
> - `docs/maintainer/ARCHITECTURE_REVIEW.md`
> - `docs/maintainer/CODEX_HANDOFF.md`
> - `docs/maintainer/REPO_FACTS.json`
> - `docs/maintainer/ACTIVE_PLAN.md`

```text
你是 Codex，在本地仓库 D:\Unity\Project\Project-Be-your-eyes 上工作。
当前仓库真实状态请先读取并遵循以下 3 份文件：
- docs/maintainer/ARCHITECTURE_REVIEW.md
- docs/maintainer/CODEX_HANDOFF.md
- docs/maintainer/REPO_FACTS.json
- docs/maintainer/ACTIVE_PLAN.md

目标版本：v5.06
分支：feature/unity-skeleton
本轮主题：Truth & Focus
原则：不再继续无序堆功能；先把 Quest/PC/Gateway 的边界、交互入口、real/mock 可观测性、frame source 命名与 Desktop Console 固化下来。

========================
0) PRECHECK（必须先做）
========================
1. git status --porcelain=v1
2. git branch --show-current
3. git rev-parse HEAD
4. Get-Content VERSION

要求：
- 分支必须是 feature/unity-skeleton
- 若 dirty：git stash push -u -m "pre-v5.06-truth-focus"
- 记录当前 HEAD 和 VERSION 到最终报告

========================
1) 版本与文档
========================
- VERSION -> v5.06
- 更新：
  - README.md
  - docs/English/RELEASE_NOTES.md
  - docs/Chinese/RELEASE_NOTES.md
- 在 docs/maintainer/RUNBOOK_QUEST3.md 中新增一节：
  - "v5.06 Truth & Focus: 如何判断当前是 real/mock/fallback"
  - "Desktop Console 的使用方式"
  - "Quest 主入口说明（HandMenu 取代 legacy wrist menu）"

========================
2) Quest 入口统一：只保留一个主交互入口
========================
当前已知问题（来自 ARCHITECTURE_REVIEW.md）：
- hand menu / smoke panel / legacy wrist menu 三套入口并存
- 风格漂移，用户不知道应该操作哪个入口
- 很多动作在 panel、menu、旧 wrist menu 都能点，造成重复与混乱

v5.06 要求：
2.1 把 BYES_HandMenu 定义为唯一主入口
- Quest 默认主入口：BYES_HandMenu
- legacy wrist menu：
  - 从 Quest3SmokeScene 默认禁用/移除
  - 仅允许在 Dev/Debug 模式下手动开启（不是默认）
- Smoke Panel：
  - 只保留状态摘要、少量 fallback 按钮（如 SelfTest / Refresh / Show Debug）
  - 不再承载完整 IA，不再承载大多数 action 按钮

2.2 HandMenu 信息架构收敛
保留 5 个页面，不要更多：
- Home
- Vision
- Voice
- SLAM
- Dev

每页职责：
Home:
- Scan Once
- Live Toggle
- Read Text
- Find (进入子选择)
- 当前状态摘要：HTTP / WS / providers real-mock badge

Vision:
- DET/SEG/DEPTH overlay toggles
- Alpha sliders
- Show Panel toggle
- Overlay Freeze / Snapshot

Voice:
- Push-to-talk
- Auto Voice Command
- Play Beep
- Speak Test
- Last Transcript / Last Spoken

SLAM:
- Start/Stop SLAM
- Show Trajectory
- Reset SLAM
- SLAM status/fps

Dev:
- Run SelfTest
- Start/Stop Record
- Open Desktop Console hint
- Export Debug Text

Find 子页或弹层：
- Door
- Exit Sign
- Stairs
- Elevator
- Restroom
- Person
- Chair
- 自定义 prompt（如果已有输入机制，否则先不做）

2.3 HandMenu 行为必须显式符合官方 Hand Menu 逻辑
- 利用/复用 XRI Hand Menu 的 palm-facing-user 显示逻辑
- 左手为默认（MenuHandedness=Left），可在 Settings 或 Dev 页切 Right/Either
- 不允许反字
- 不允许“手没翻过来也出现”
- 不允许“超过正面角度立刻消失得很突兀”：
  - 加 0.2~0.3s hysteresis / smoothing

========================
3) Smoke Panel 重新定位：状态面板，不是功能面板
========================
3.1 只保留这些字段（足够了）：
- HTTP reachable
- WS connected
- Frame source
- Last Upload / Last E2E
- Last OCR / Last FIND / Last TARGET / Last RISK
- Provider badges（DET/SEG/DEPTH/SLAM/ASR/TTS）
- SelfTest summary
- Record status
- Mode

3.2 去掉/下移以下职责：
- 不再承担大量 Action 按钮
- 不再承担完整菜单
- 不再承载 legacy wrist 功能

3.3 增加“Truth fields”
面板必须能直接显示：
- Frame Source: pca-real / pca-fallback / rendertexture-fallback
- DET: real/mock, model, device
- SEG: real/mock, model, device
- DEPTH: real/mock, model, device
- SLAM: real/mock, backend
- ASR: real/mock, backend
- TTS: local-real / mock / muted
- Last Evidence TS（最近一次真结果时间）
- Last Overlay Kind

要求：
- 这些字段不要每帧疯狂字符串拼接；状态变化驱动刷新，或 1s 节流刷新

========================
4) Frame Source “说真话”：修正 PCA 抽象与命名
========================
根据 ARCHITECTURE_REVIEW.md / CODEX_HANDOFF.md：
- 当前所谓 ByesPcaFrameSource 其实不是“真 Meta PCA”，而是 AR CPU image fallback
- 这是严重的命名误导

v5.06 必须修正：
4.1 重命名或重新分层
方案优先级：
A. 重命名类/状态，不一定强行改文件名（如果大改影响太大）：
   - 保留脚本路径可接受，但 UI/日志/状态中绝不能显示“PCA”当作已接通
B. 更好：引入新的抽象名：
   - ByesCameraFrameSource (interface/abstract)
   - ByesArCpuImageFrameSource
   - ByesPcaFrameSource（只有真 PCA 接通时才存在）

4.2 /api/capabilities 与 Quest UI 一致
- capabilities 中新增/修正：
  - frameSource: ar_cpuimage_fallback / pca_real / rendertexture_fallback
  - frameSourceEvidence: why
- Quest Panel / Desktop Console 必须显示同样的文案

4.3 不要求 v5.06 真正接入 PCA
- 这版目标是“说真话 + 统一抽象”
- 真 PCA 放到 v5.07（除非你发现已有可靠实现且改动很小）

========================
5) Desktop Console 升级成“事实源控制台”
========================
当前 /ui 存在，但根据 review 仍偏开发工具，不够“一眼看懂”
v5.06 目标：
5.1 /ui 首页必须有 4 个卡片：
- Current Frame Source（含 fallback reason）
- Providers（DET/SEG/DEPTH/SLAM/ASR/TTS，real/mock/model/device）
- Latest Overlay Preview（det/seg/depth 各一张缩略图）
- Latest Run Package / Record State

5.2 /ui 增加：
- 事件尾流（最近 20 条关键 event，不显示健康检查 spam）
- Latest provider evidence（每个 provider 最后成功时间、infer ms、fps）
- 当前 mode / current target session / current record session
- 一键动作（按钮）：
  - Scan Once
  - Read Text
  - Find Door
  - Start/Stop Record
  - Run SelfTest trigger（如果有）

5.3 控制台要明确 mock/real
- 用颜色标签：
  - green = real
  - gray = mock
  - yellow = fallback
  - red = unavailable
- 不允许用户继续猜“到底是不是 mock”

========================
6) Provider evidence 统一化（Quest + Desktop 同步）
========================
目标：所有 provider 都有统一的 evidence 结构
实现：
6.1 Gateway 统一一个 provider evidence 数据结构（如果已有，扩展）
字段至少包括：
- capability
- backend
- model
- device
- is_mock
- reason
- last_success_ts
- last_infer_ms
- fps_estimate
- source (frame/assist/record/replay)

6.2 evidence 来源
- 每次 provider 真正成功跑一次，必须更新 evidence
- fallback / unavailable 也要写 reason
- 通过 `/api/providers` 和 `/api/capabilities` 返回
- 通过 WS 可选发一个 `provider.evidence.v1`（若太重，可只 Quest 本地拉）

6.3 Quest panel / Desktop Console 都必须读同一份 evidence
- 不允许 Quest 写一套判断逻辑，Desktop 再写一套

========================
7) Legacy / 重复系统清理（最少但必须）
========================
根据 CODEX_HANDOFF.md 的 fragile files 与 architecture smells：
7.1 清理/禁用 legacy wrist menu 默认入口
- 保留代码可以，但 Quest3SmokeScene 默认不能再实例化/显示
- 如果 installer 还会注入，修 installer

7.2 清理 Guide/Coaching 残留
- 确保 Quest3SmokeScene 启动后不再出现模板 guide wrist menu
- 如果需要，复查 ByesMrTemplateGuideDisabler 是否仍覆盖所有对象名/类型

7.3 不要再继续把功能塞进 ByesQuest3ConnectionPanelMinimal
- 这次只做“减法/重组”
- 如果必须新增字段，尽量抽到单独 provider status model / desktop console model

========================
8) 录制与回放链路“证据化”
========================
v5.06 不加新功能，但要让你更容易验证：
8.1 Quest 录制 Start/Stop 之后
- Panel 显示当前 runId / recordingPath（短路径显示）
- Desktop Console 也显示 recording 状态
8.2 replay/report
- 在 Desktop Console 显示最近一次 run package 路径
- 若存在最近报告 report.json/report.md，显示一个摘要（pass/fail/counts）

========================
9) 门禁（必须全绿）
========================
按顺序跑：
- python tools/check_unity_meta.py
- python tools/check_docs_links.py
- python tools/check_unity_layering.py
- python tools/check_unity_legacy_input.py

- cd Gateway
- python -m pytest -q -n auto --dist loadgroup
- python scripts/lint_run_package.py --run-package tests/fixtures/run_package_with_events_v1_min
- python scripts/run_regression_suite.py --suite regression/suites/baseline_suite.json --baseline regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
- python scripts/run_regression_suite.py --suite regression/suites/contract_suite.json --baseline regression/baselines/baseline.json --fail-on-drop --fail-on-critical-fn
- python scripts/verify_contracts.py --check-lock
- cd ..

- cmd /c tools\unity\build_quest3_android.cmd

要求：
- Android build summary 必须 SUCCEEDED
- Gateway pytest 必须全绿
- tools checks 必须全绿

========================
10) 提交与推送
========================
- VERSION = v5.06
- git add -A
- git commit -m "feat(v5.06): truth & focus (single quest entrypoint + real/mock evidence + desktop console hardening + frame-source truth + docs)"
- git push origin feature/unity-skeleton

========================
11) 最终输出给我（必须包含）
========================
A. commit hash / VERSION / push 结果
B. 改动文件清单（Unity / Gateway / Docs / Tools 分组）
C. 这轮删掉/禁用/退役了哪些 legacy 入口
D. /api/capabilities 与 /ui 的新字段与截图建议
E. Quest 手工验收步骤（不超过 8 步）
F. 若你在实现中发现“真 PCA 已有低风险接入路径”，单独写在最后一节 “PCA path candidate”
```
