# DECISIONS

Canonical architecture decisions that should not be re-litigated without explicit maintainer approval.
- Source: `docs/maintainer/ARCHITECTURE_REVIEW_v5.04.md`, `docs/maintainer/WORKFLOW_HANDOFF_v5.04.md`, `docs/maintainer/REPO_FACTS_v5.04.json`, the approved `v5.06 Truth & Focus` design, and the approved `v5.07 True Capture + True Voice` design.
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
- Capture truth may only surface as `pca_real`, `ar_cpuimage_fallback`, `rendertexture_fallback`, or `unavailable`.
- If the runtime cannot prove true Meta PCA, it must surface a fallback or unavailable state together with a reason.
- ASR and TTS are separate truth chains: ASR is Gateway-side recognition evidence; TTS is Quest-local playback evidence.
- `mock`, `fallback`, `unavailable`, and `muted` states must be explicit in both Quest UI and Desktop Console.

## System Boundaries

- Quest owns capture initiation, hand/menu UI, HUD display, passthrough, local TTS, local guidance feedback, and recording triggers.
- PC owns heavy inference, replay, reporting, regression, model or weight management, and desktop observability.
- Gateway owns contracts, event normalization, API routing, provider orchestration, frame or asset caching, and recording package management.

## Change Discipline

- Contracts remain stable unless intentionally revised and re-locked.
- Truth alignment should be implemented additively first; avoid destructive field removals when compatibility is still needed.
- Version-specific execution briefs are external working documents and are not tracked in the repository; long-term memory belongs under `docs/maintainer/`.
- pySLAM remains an optional external service and must not be folded into the default realtime smoke path or CI gates.
- Hand Menu remains the primary Quest entry; true-capture and true-voice evidence should be layered into existing surfaces instead of adding a new interaction plane.
