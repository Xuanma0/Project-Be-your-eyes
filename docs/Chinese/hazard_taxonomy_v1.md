# 危险分类法 v1

## 规范 hazardKind
- `dropoff`
- `stair_down`
- `obstacle_close`
- `unknown_depth`
- `low_clearance`

## 别名映射
- `stair_down_edge` -> `dropoff`
- `drop_off` -> `dropoff`
- `ledge` -> `dropoff`
- `cliff` -> `dropoff`
- `stairs_down` -> `stair_down`
- `stairs` -> `stair_down`
- `stairdown` -> `stair_down`
- `obstacle` -> `obstacle_close`
- `obstacle_near` -> `obstacle_close`
- `unknown` -> `unknown_depth`

为保持向后兼容，允许未知 kind，但会在 lint/report 中作为 warning 报出。

## 严重级别策略
- `critical`：需立即停止 / 最高优先级安全警报
- `warning`：近期风险；用户应减速/扫描
- `info`：低置信度或信息性风险提示

## 该分类的使用位置

- `risk.hazards` 事件负载归一化。
- planner 安全规则与确认行为。
- 报告质量惩罚（`critical FN` 硬门禁）。
- costmap / planner context 摘要中的障碍语义文本化。
