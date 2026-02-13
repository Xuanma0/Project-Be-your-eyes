# POV Planner Adapter v1

This document defines the deterministic adapter from `pov.ir.v1` to `byes.action_plan.v1`.

## Scope

- Provider: `BYES_PLANNER_PROVIDER=pov` in `Gateway/services/planner_service`.
- Input: `runPackagePath` pointing to a run package with `pov/pov_ir_v1.json`.
- Output: strict `byes.action_plan.v1` validated by `validate_action_plan.py`.

## Mapping Rules (MVP)

1. Decisions -> actions:
- Decision text contains stop/critical/danger/hazard: emit `stop` (blocking).
- Decision text contains confirm/wait/clarify/ask: emit `confirm` (blocking).

2. Highlights -> speak:
- Merge up to first two highlight texts.
- Emit `speak` action with `payload.source="pov"`.
- Add `payload.sourceDecisionIds` by matching highlight `tMs` into decision windows (`t0Ms..t1Ms`), else nearest prior decision.

3. Risk level:
- Any critical-like decision/event -> `riskLevel=critical`.
- Else warning/high signals -> `riskLevel=medium`.
- Else `riskLevel=low`.

4. Action constraints:
- Validate and trim actions with `constraints.maxActions`.
- Preserve deterministic ordering by `priority`.

## Fallback

If `pov/pov_ir_v1.json` is missing or invalid:
- fallback to reference planner,
- set planner metadata:
  - `fallbackUsed=true`
  - `fallbackReason=missing_pov_ir` or `pov_adapter_error`
  - `jsonValid=false`

## Alignment Metrics

`report.json.povPlan` provides adapter-consumption evidence:
- `decisionCoverage`
- `actionCoverage`
- `consistencyWarnings`
- `warnings`

Contract fixture: `Gateway/tests/fixtures/pov_plan_min`.
