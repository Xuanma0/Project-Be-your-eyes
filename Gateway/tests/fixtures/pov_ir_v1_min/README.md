# POV IR v1 Contract Fixture

This fixture is the shared contract sample for `pov.ir.v1` -> BYES `events_v1` ingest.

Rules:
- any interface field change must update `schemas/pov_ir_v1.schema.json` first,
- then sync POV-compiler output and this fixture together,
- and keep contract tests/regression suite green.
