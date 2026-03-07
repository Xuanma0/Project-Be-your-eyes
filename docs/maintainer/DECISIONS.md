# DECISIONS

Canonical architecture decisions that should not be re-litigated without explicit maintainer approval.
- Source: `docs/maintainer/ARCHITECTURE_REVIEW_v5.04.md`, `docs/maintainer/CODEX_HANDOFF_v5.04.md`, `docs/maintainer/REPO_FACTS_v5.04.json`, and the approved `v5.06 Truth & Focus` design.
- Updated: `2026-03-07`.

## Interaction and UX

- `BYES_HandMenu` is the sole primary Quest interaction entry.
- Smoke Panel is a status summary surface, not the primary action surface.
- Legacy wrist menu is not the default main entry; if it remains, it is debug-only or explicitly opt-in.
- Quest should favor fewer, clearer surfaces over multiple overlapping control planes.

## Runtime Truth Model

- `real / mock / fallback` state must be consistent on both Quest and Desktop.
- Desktop Console is one of the runtime fact sources; it is not optional debug chrome.
- Panel-only state is insufficient to claim a capability works. Quest-visible output or runtime evidence must agree.
- Until true Meta PCA exists, fallback capture must not be labeled or implied as real PCA.

## System Boundaries

- Quest owns capture initiation, hand/menu UI, HUD display, passthrough, local TTS, local guidance feedback, and recording triggers.
- PC owns heavy inference, replay, reporting, regression, model or weight management, and desktop observability.
- Gateway owns contracts, event normalization, API routing, provider orchestration, frame or asset caching, and recording package management.

## Change Discipline

- Contracts remain stable unless intentionally revised and re-locked.
- Truth alignment should be implemented additively first; avoid destructive field removals when compatibility is still needed.
- New version execution work belongs under `docs/codex/`; long-term memory belongs under `docs/maintainer/`.
