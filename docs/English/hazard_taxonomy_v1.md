# Hazard Taxonomy v1

## Canonical hazardKind
- `dropoff`
- `stair_down`
- `obstacle_close`
- `unknown_depth`
- `low_clearance`

## Alias mapping
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

Unknown kinds are allowed for backward compatibility, but they are reported as warnings in lint/report.

## Severity policy
- `critical`: immediate stop / highest priority safety warning
- `warning`: near-term risk; user should slow down/scan
- `info`: low-confidence or informational risk cue

## Where this taxonomy is used

- `risk.hazards` event payload normalization.
- planner safety rules and confirmation behavior.
- report quality penalties (`critical FN` hard gate).
- costmap/planner-context summaries when obstacle semantics are mapped into prompt text.
