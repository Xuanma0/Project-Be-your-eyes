# PR_DESCRIPTION (Draft)

## Title
Docs-first audit + README unification + planner key compatibility fix (`v4.87`)

## What changed

### Documentation systemization
- Added `docs/maintainer/` bundle:
  - `REPO_FACTS.json`
  - `AUDIT_REPO.md`
  - `RUNBOOK_LOCAL.md`
  - `API_INVENTORY.md`
  - `CONFIG_MATRIX.md`
  - `SECURITY_REVIEW.md`
  - `OPEN_QUESTIONS.md`
  - `MAINTAINER_BRIEF.md`

### Version policy unification
- Added root `VERSION` (`v4.87`).
- Rewrote root `README.md` for contributor runability (offline + realtime paths).
- Updated `docs/English/README.md` and `docs/Chinese/README.md` to point current version to `VERSION`.
- Added version-policy note at top of both release notes files.

### Config examples
- Added root `.env.example` with placeholder-only values (`YOUR_KEY_HERE`), no real secrets.

### Compatibility fix (low risk)
- `planner_service` openai mode now accepts:
  - primary: `BYES_PLANNER_LLM_API_KEY`
  - fallback: `OPENAI_API_KEY`
- `model_manifest` llm requirement now considers either key as satisfied.

## Why
- Align operational truth across docs/runbook/API/config/security.
- Remove ambiguity between runtime key usage and model-manifest checks.
- Make first-run paths reproducible for maintainers and external reviewers.

## Validation commands run

1. Planner compatibility and llm fallback tests:
```bash
cd Gateway
python -m pytest -q tests/test_planner_openai_key_compat.py tests/test_llm_provider_fallback.py tests/test_llm_provider_invalid_json.py
```
Result: `3 passed`.

2. Model manifest related checks:
```bash
cd Gateway
python -m pytest -q tests/test_api_models_endpoint.py tests/test_verify_models_script_smoke.py
```
Result: `2 passed`.

## Notes
- Working branch for this task: `docs/audit-readme-refresh`.
- Pre-existing dirty changes were stashed before edits:
  - `git stash push -u -m "codex-docs-prep"`
