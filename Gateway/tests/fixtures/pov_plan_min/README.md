# POV Plan Contract Fixture

This fixture locks the `pov.ir.v1 -> byes.action_plan.v1` adapter contract.

Rules:
- update `schemas/pov_ir_v1.schema.json` first for interface changes,
- then update adapter mapping (`services/planner_service/pov_adapter.py`),
- and keep `expected/plan_action_plan_v1.json` + contract tests green.
