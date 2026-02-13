# BeYourEyes Architecture

## Goal
This folder isolates domain logic from Unity runtime concerns.
Core rules stay deterministic, testable, and independent from engine APIs.
Unity integration is routed through adapters and presenters.

## Top-Level Layout
`Core/` contains business logic and contracts.
`Adapters/` connects external systems to internal contracts.
`Presenters/` converts domain state to Unity-facing behavior.
`Features/` composes use cases from Core + Unity pieces.
`Config/` stores ScriptableObject or JSON config assets.
`Scenes/` holds scene assets related to BeYourEyes flows.
`Docs/` contains architecture notes and team conventions.

## Core Responsibilities
`Core/Events` defines immutable domain event types.
`Core/EventBus` defines publish/subscribe abstractions and in-memory bus logic.
`Core/StateMachine` defines state, transitions, and guards.
`Core/Scheduling` defines time, retry, debounce, and sequencing abstractions.
Core code must not reference `UnityEngine` or scene objects.
Core code should prefer interfaces over concrete IO dependencies.

## Adapter Responsibilities
`Adapters/Networking` wraps HTTP/WebSocket/services behind Core interfaces.
`Adapters/Sensors` wraps device or XR sensor streams into Core-friendly models.
Adapters may depend on Unity APIs or third-party SDKs.
Adapters must not contain feature orchestration logic.

## Presenter Responsibilities
`Presenters/Audio` maps domain events to audio cues and playback policies.
`Presenters/DebugHUD` renders diagnostics and runtime state for developers.
Presenters can read Core state but should not mutate domain rules directly.

## Feature Layer
`Features/` owns use-case wiring, lifecycle orchestration, and dependency graph setup.
Features may coordinate adapters, core services, and presenters.
Keep feature scripts small and focused on composition.

## Assembly Boundaries
`BeYourEyes.Core.asmdef` is engine-agnostic with `noEngineReferences=true`.
`BeYourEyes.Unity.asmdef` references `BeYourEyes.Core` for integration code.
Unity-facing scripts should live outside Core unless they are pure C# models.

## Dependency Direction
Allowed: Unity -> Core.
Allowed: Adapters/Presenters/Features -> Core.
Not allowed: Core -> Unity.
Not allowed: Core -> concrete infrastructure implementation.

## Team Conventions
Add new domain rules in Core first, then expose via interfaces.
Implement platform details in Adapters, visualization in Presenters.
Document major boundary changes in this file during PRs.

## Event Contract
All core events carry `EventEnvelope` with `timestampMs`, `coordFrame`, `confidence`, `ttlMs`, `source`.
`timestampMs` is producer clock time in milliseconds.
`coordFrame` identifies the coordinate basis for spatial values.
`confidence` is normalized to `[0,1]`.
`ttlMs <= 0` is normalized to `1000ms` to avoid accidental immediate drop.
Consumers should call `IsExpired(nowMs)` before handling.
Expired events are dropped and must not update state or UI.

## Minimal Closed Loop
`MockEventSource` publishes `RiskEvent` and `PerceptionEvent` to `EventBus`.
`PromptScheduler` consumes those events and emits `PromptEvent`.
`DebugAudioPresenter` subscribes `PromptEvent` and logs TTS text.
Runtime path: `MockEventSource -> EventBus -> PromptScheduler -> PromptEvent -> DebugAudioPresenter`.

## Gateway Runtime Loop
`GatewayPoller` can replace `MockEventSource` as the upstream event producer.
It polls `GET /api/mock_event`, converts DTO to core events, and publishes to `EventBus`.
Runtime path: `GatewayPoller -> EventBus -> PromptScheduler -> PromptEvent -> DebugAudioPresenter`.

## WebSocket + SafeMode
`GatewayWsClient` is the preferred upstream in Editor/Windows and streams `/ws/events`.
Incoming WS JSON is queued from a background task, then parsed/published on Unity main thread.
WS `gateway_disconnected` or HTTP `gateway_unreachable` enables SafeMode in `PromptScheduler`.
SafeMode keeps risk prompts active and silences perception prompts until `gateway_connected`.

## DebugHUD Metrics
`DebugHudPresenter` shows live gateway connectivity, SafeMode flag, reconnect attempts, and RTT.
It also tracks the latest Risk/Perception/Dialog/System event summary and timestamp.
HUD is built with native `UnityEngine.UI` Canvas + Text (no extra plugin dependency).
SafeMode display reads `AppServices.Scheduler.SafeModeEnabled` directly.
