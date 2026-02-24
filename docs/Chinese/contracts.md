# 契约冻结（v4.41）

本仓库在 `Gateway/contracts/` 中冻结了机器可读的接口契约，以便 POV-Compiler 与 BYES 校验同一套 API 表面。

## 冻结内容

- `Gateway/contracts/pov.ir.v1.json`
- `Gateway/contracts/byes.event.v1.json`
- `Gateway/contracts/byes.action_plan.v1.json`
- `Gateway/contracts/byes.plan_request.v1.json`
- `Gateway/contracts/byes.seg.v1.json`
- `Gateway/contracts/byes.depth.v1.json`
- `Gateway/contracts/byes.ocr.v1.json`
- `Gateway/contracts/byes.slam_pose.v1.json`
- `Gateway/contracts/byes.models.v1.json`
- `Gateway/contracts/byes.seg_request.v1.json`
- `Gateway/contracts/pov.context.v1.json`
- `Gateway/contracts/frame.input.v1.json`
- `Gateway/contracts/frame.ack.v1.json`
- `Gateway/contracts/frame.e2e.v1.json`
- `Gateway/contracts/plan.context_alignment.v1.json`
- `Gateway/contracts/plan.context_pack.v1.json`
- `Gateway/contracts/seg.context.v1.json`
- `Gateway/contracts/slam.context.v1.json`
- `Gateway/contracts/costmap.context.v1.json`
- `Gateway/contracts/byes.costmap.v1.json`
- `Gateway/contracts/byes.costmap_fused.v1.json`
- `Gateway/contracts/contract.lock.json`（sha256 锁文件）

截至 `v4.82`，`Gateway/contracts/byes.depth.v1.json` 也增加了可选 `meta` 字段，用于深度时序一致性分析：
- `provider`
- `refViewStrategy`
- `poseUsed`
- `warningsCount`

这些字段是可选且向后兼容，不会破坏历史回放包。

## 为什么重要

- Schema 文件定义协议。
- `contract.lock.json` 固定每个文件的精确哈希。
- CI 与契约套件会校验 lock，阻止意外漂移。

## 本地校验

```powershell
python Gateway/scripts/verify_contracts.py --check-lock
```

如果是有意修改 schema：

```powershell
python Gateway/scripts/verify_contracts.py --write-lock
python Gateway/scripts/verify_contracts.py --check-lock
```

## /api/contracts

Gateway 暴露只读契约索引：

```powershell
curl http://127.0.0.1:8000/api/contracts
```

响应包含：

- `versions`：来自 `contract.lock.json` 的 version/path/sha256/updatedAtMs
- `runtimeDefaults`：关键运行时契约元数据（POV 上下文预算、规划器默认值、风险阈值默认值）

排查 schema 漂移时，请优先核对该接口返回的 `byes.depth.v1` 哈希。

## POV-Compiler 同步流程

推荐同步到 POV-Compiler：

1. 将 `Gateway/contracts/` 和 `Gateway/contracts/contract.lock.json` 复制到 `vendor/contracts/`。
2. 在 POV-Compiler CI 中加入同样的校验步骤。
3. 发生契约变更时：更新 schema -> 写入 lock -> 同步更新两个仓库 -> 两侧 CI 都通过。
