# Contracts Freeze (v4.41)

This repository freezes machine-readable interface contracts in `Gateway/contracts/` so POV-Compiler and BYES can verify the same API surface.

## What is frozen

- `Gateway/contracts/pov.ir.v1.json`
- `Gateway/contracts/byes.event.v1.json`
- `Gateway/contracts/byes.action_plan.v1.json`
- `Gateway/contracts/pov.context.v1.json`
- `Gateway/contracts/contract.lock.json` (sha256 lock file)

## Why this matters

- Schema files define the protocol.
- `contract.lock.json` pins exact file hashes.
- CI and contract suite verify the lock so accidental drift is blocked.

## Verify locally

```powershell
python Gateway/scripts/verify_contracts.py --check-lock
```

If schema files changed intentionally:

```powershell
python Gateway/scripts/verify_contracts.py --write-lock
python Gateway/scripts/verify_contracts.py --check-lock
```

## /api/contracts

Gateway exposes a read-only contracts index:

```powershell
curl http://127.0.0.1:8000/api/contracts
```

The response includes:

- `versions`: version/path/sha256/updatedAtMs from `contract.lock.json`
- `runtimeDefaults`: key runtime contract metadata (POV context budget, planner defaults, risk threshold defaults)

## POV-Compiler sync workflow

Recommended sync into POV-Compiler:

1. Copy `Gateway/contracts/` and `Gateway/contracts/contract.lock.json` into `vendor/contracts/`.
2. Add the same verify step in POV-Compiler CI.
3. For contract changes: update schema -> write lock -> update both repos -> pass CI on both sides.
